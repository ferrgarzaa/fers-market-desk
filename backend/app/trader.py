"""Live simulated trading bot: SMA crossover on COMPLETED candles of one interval.

Event handling (called by the Hub with every candle revision the store produces):
* any revision of a candle that started after a pending order's signal candle
  -> fill that order at the candle's OPEN (the first price of the next interval)
* a candle becoming complete for the first time (newer than the last one processed)
  -> its close is fed to the CrossoverDetector; a BUY/SELL creates a PENDING order
* revisions of candles already processed (late ticks) are recorded by the store but do NOT
  re-run past decisions: a decision is final once made, exactly as it would be for a trader.
* the provisional (unfinished) candle is only *peeked* to show a provisional signal; it never trades.

On startup the detector is primed with the stored completed candles (no orders are placed while
priming), so the SMAs are ready immediately instead of after 21 live minutes.
"""
from __future__ import annotations

from .broker import BrokerConfig, SimBroker
from .indicators import CrossoverDetector
from .store import CandleStore


class LiveTrader:
    def __init__(self, store: CandleStore, symbols: list[str], interval: str, fast: int, slow: int,
                 cfg: BrokerConfig, now_ms: int):
        self.store, self.symbols, self.interval = store, symbols, interval
        self.fast, self.slow = fast, slow
        self.broker = SimBroker(store.conn, "live", cfg, kind="live",
                                params={"strategy": f"SMA {fast}/{slow} crossover", "interval": interval},
                                now_ms=now_ms)
        self.det = {s: CrossoverDetector(fast, slow) for s in symbols}
        self.last_bar = {s: -1 for s in symbols}
        self.last_signal: dict[str, dict] = {}

    def prime(self):
        for s in self.symbols:
            self.det[s] = CrossoverDetector(self.fast, self.slow)
            for c in self.store.get_candles(s, self.interval, limit=5000):
                if c["is_complete"]:
                    self.det[s].update(c["close"])
                    self.last_bar[s] = c["time"]

    def on_candles(self, candles: list[dict], now_ms: int) -> dict:
        out = {"fills": [], "orders": []}
        for c in sorted((c for c in candles if c["interval"] == self.interval), key=lambda c: c["time"]):
            s = c["symbol"]
            if s not in self.det:
                continue
            out["fills"] += self.broker.fill_pending(s, c["time"], c["open"], now_ms)
            if c["is_complete"] and c["time"] > self.last_bar[s]:
                self.last_bar[s] = c["time"]
                f, sl, sig = self.det[s].update(c["close"])
                if sig:
                    reason = (f"SMA {self.fast}/{self.slow} cross {'up' if sig == 'BUY' else 'down'} "
                              f"on completed {self.interval} candle")
                    order = self.broker.submit(s, sig, c["time"], c["close"], reason, now_ms, f, sl)
                    self.last_signal[s] = {"time": c["time"], "signal": sig, "close": c["close"],
                                           "order_status": order["status"]}
                    out["orders"].append(order)
        return out

    def strategy_status(self, symbol: str) -> dict:
        d = self.det.get(symbol)
        if d is None:
            return {}
        prov = None
        cs = self.store.get_candles(symbol, self.interval, limit=2)
        if cs and not cs[-1]["is_complete"] and cs[-1]["time"] > self.last_bar[symbol]:
            f, s, sig = d.peek(cs[-1]["close"])
            prov = {"time": cs[-1]["time"], "sma_fast": f, "sma_slow": s, "signal": sig}
        return {"symbol": symbol, "interval": self.interval, "fast": self.fast, "slow": self.slow,
                "sma_fast": d.fast.value, "sma_slow": d.slow.value, "state": d.state,
                "bars_seen": d.bars, "last_complete_bar": self.last_bar[symbol],
                "last_signal": self.last_signal.get(symbol), "provisional": prov}
