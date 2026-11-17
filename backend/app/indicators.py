"""Simple moving averages and the SMA crossover rule.

Definitions (docs/STRATEGY.md has the full explanation)
-------------------------------------------------------
SMA(n) at bar i  = mean(close[i-n+1 .. i]); undefined (None) for the first n-1 bars.
diff(i)          = SMA_fast(i) - SMA_slow(i)
Crossover rule   = remember the sign of the last NON-ZERO diff.
                   BUY  at bar i when that sign was negative and diff(i) > 0
                   SELL at bar i when that sign was positive and diff(i) < 0
                   A diff of exactly 0 is a touch, not a cross: it never signals and does not
                   reset the remembered sign (so above -> touch -> above is no signal).
                   The first bar where both SMAs exist only initialises the sign.

Two implementations exist on purpose and are tested against each other and against pandas:
* batch:       sma_batch / crossover_signals over a whole list (used for the chart and backtest checks)
* incremental: IncrementalSMA / CrossoverDetector, one bar at a time (used by the live bot and the
               event-driven backtest, so a decision can never see a later bar).

Unfinished candles: only COMPLETE candles feed the strategy. `indicator_series` may append the
provisional candle for display; its point is flagged provisional=True and its signal is reported as
a *provisional signal* that is never traded.
"""
from __future__ import annotations

from collections import deque
from typing import Optional, Sequence


def sma_batch(closes: Sequence[float], n: int) -> list[Optional[float]]:
    if n < 1:
        raise ValueError("SMA window must be >= 1")
    out: list[Optional[float]] = []
    s = 0.0
    for i, c in enumerate(closes):
        s += c
        if i >= n:
            s -= closes[i - n]
        out.append(s / n if i >= n - 1 else None)
    return out


class IncrementalSMA:
    """O(1) rolling mean. To avoid floating-point drift the sum is recomputed from the window
    every `n` updates (cheap, and keeps batch and incremental results identical to ~1e-9)."""

    def __init__(self, n: int):
        if n < 1:
            raise ValueError("SMA window must be >= 1")
        self.n = n
        self.window: deque[float] = deque()
        self.total = 0.0
        self._since_resum = 0

    def add(self, close: float) -> Optional[float]:
        self.window.append(close)
        self.total += close
        if len(self.window) > self.n:
            self.total -= self.window.popleft()
        self._since_resum += 1
        if self._since_resum >= self.n:
            self.total = sum(self.window)
            self._since_resum = 0
        return self.value

    def peek(self, close: float) -> Optional[float]:
        """SMA if `close` were the next bar, without changing state (for provisional signals)."""
        if len(self.window) + 1 < self.n:
            return None
        drop = self.window[0] if len(self.window) == self.n else 0.0
        return (self.total - drop + close) / self.n

    @property
    def value(self) -> Optional[float]:
        return self.total / self.n if len(self.window) == self.n else None


def _cross(last_sign: int, diff: float) -> Optional[str]:
    if last_sign < 0 and diff > 0:
        return "BUY"
    if last_sign > 0 and diff < 0:
        return "SELL"
    return None


def _sign(x: float) -> int:
    return 1 if x > 0 else -1 if x < 0 else 0


class CrossoverDetector:
    """Incremental SMA(fast) / SMA(slow) crossover over completed bars."""

    def __init__(self, fast: int, slow: int):
        if not fast < slow:
            raise ValueError("fast window must be shorter than slow window")
        self.fast, self.slow = IncrementalSMA(fast), IncrementalSMA(slow)
        self.last_sign = 0          # sign of last non-zero diff (0 = not initialised)
        self.bars = 0

    def update(self, close: float) -> tuple[Optional[float], Optional[float], Optional[str]]:
        """Feed one COMPLETED bar. Returns (sma_fast, sma_slow, signal)."""
        self.bars += 1
        f, s = self.fast.add(close), self.slow.add(close)
        if f is None or s is None:
            return f, s, None
        diff = f - s
        sig = _cross(self.last_sign, diff)
        if diff != 0:
            self.last_sign = _sign(diff)
        return f, s, sig

    def peek(self, close: float) -> tuple[Optional[float], Optional[float], Optional[str]]:
        """What the values/signal WOULD be if the unfinished candle closed at `close`."""
        f, s = self.fast.peek(close), self.slow.peek(close)
        if f is None or s is None:
            return f, s, None
        return f, s, _cross(self.last_sign, f - s)

    @property
    def state(self) -> str:
        return {1: "bullish", -1: "bearish"}.get(self.last_sign, "warming up")


def crossover_signals(closes: Sequence[float], fast: int, slow: int) -> list[Optional[str]]:
    """Batch version of the crossover rule (same semantics as CrossoverDetector)."""
    f, s = sma_batch(closes, fast), sma_batch(closes, slow)
    out: list[Optional[str]] = []
    last = 0
    for a, b in zip(f, s):
        if a is None or b is None:
            out.append(None)
            continue
        d = a - b
        out.append(_cross(last, d))
        if d != 0:
            last = _sign(d)
    return out


def indicator_series(candles: list[dict], fast: int, slow: int) -> dict:
    """Indicator points for the chart. Completed candles define the values and confirmed signals;
    trailing provisional candles are evaluated with `peek` and flagged provisional."""
    det = CrossoverDetector(fast, slow)
    points = []
    complete = [c for c in candles if c["is_complete"]]
    for c in complete:
        f, s, sig = det.update(c["close"])
        points.append({"time": c["time"], "fast": f, "slow": s, "signal": sig, "provisional": False})
    last_t = complete[-1]["time"] if complete else -1
    for c in candles:
        if not c["is_complete"] and c["time"] > last_t:
            f, s, sig = det.peek(c["close"])
            points.append({"time": c["time"], "fast": f, "slow": s, "signal": sig, "provisional": True})
            break  # at most one unfinished candle is evaluated
    return {"fast": fast, "slow": slow, "state": det.state, "points": points}
