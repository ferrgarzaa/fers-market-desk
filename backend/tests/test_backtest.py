"""Backtest: hand example, no look-ahead, provisional candles excluded, live bot == backtest."""
import random

import pytest

from app.backtest import run_backtest
from app.broker import BrokerConfig
from app.db import connect
from app.store import CandleStore
from app.trader import LiveTrader

from .test_indicators import CLOSES

ZERO = BrokerConfig(100_000, fee_rate=0, slippage=0, alloc=0.10)
COSTS = BrokerConfig(100_000, fee_rate=0.001, slippage=0.0005, alloc=0.10)


def bars_from_closes(closes, start_open=None):
    out, prev = [], start_open if start_open is not None else closes[0]
    for i, c in enumerate(closes):
        out.append({"time": 60 * i, "open": prev, "high": max(prev, c), "low": min(prev, c), "close": c,
                    "is_complete": True})
        prev = c
    return out


def random_bars(n, seed=11):
    rng = random.Random(seed)
    closes, p = [], 100.0
    for _ in range(n):
        p *= 1 + rng.gauss(0, 0.006)
        closes.append(round(p, 4))
    return bars_from_closes(closes)


def test_hand_example_trades_at_next_open():
    r = run_backtest(bars_from_closes(CLOSES), "X", "1m", 2, 4, ZERO)
    assert [(s["time"], s["signal"]) for s in r["signals"]] == [(360, "BUY"), (540, "SELL")]
    t = r["trades"]
    # BUY signalled on bar 6 close (12) -> filled at bar 7 OPEN = 12 ; SELL on bar 9 -> bar 10 open = 9
    assert [(x["time"], x["side"], x["fill_price"]) for x in t] == [(420, "BUY", 12), (600, "SELL", 9)]
    assert t[0]["qty"] == pytest.approx(10_000 / 12)
    assert t[1]["realized_pnl"] == pytest.approx((9 - 12) * 10_000 / 12)   # -2,500
    m = r["metrics"]
    assert m["final_equity"] == pytest.approx(97_500) and m["round_trips"] == 1 and m["wins"] == 0
    assert m["total_return_pct"] == pytest.approx(-2.5)


@pytest.mark.parametrize("k", [60, 150, 333, 480])
def test_no_look_ahead_truncated_history_gives_identical_decisions(k):
    bars = random_bars(600)
    full = run_backtest(bars, "X", "1m", 9, 21, COSTS)
    part = run_backtest(bars[:k], "X", "1m", 9, 21, COSTS)
    cut = bars[k - 1]["time"]
    assert part["signals"] == [s for s in full["signals"] if s["time"] <= cut]
    assert part["trades"] == [t for t in full["trades"] if t["time"] <= cut]
    assert part["equity"] == full["equity"][:k]


def test_changing_the_future_cannot_change_past_decisions():
    bars = random_bars(400)
    altered = [dict(b) for b in bars]
    for b in altered[250:]:
        b["close"] *= 1.5
        b["open"] *= 1.5
    a, b = run_backtest(bars, "X", "1m", 9, 21, COSTS), run_backtest(altered, "X", "1m", 9, 21, COSTS)
    cut = bars[249]["time"]
    assert [s for s in a["signals"] if s["time"] <= cut] == [s for s in b["signals"] if s["time"] <= cut]


def test_provisional_candle_is_excluded():
    bars = bars_from_closes(CLOSES)
    bars.append({"time": 720, "open": 6, "high": 50, "low": 6, "close": 50, "is_complete": False})
    r = run_backtest(bars, "X", "1m", 2, 4, ZERO)
    assert r["metrics"]["bars"] == len(CLOSES)
    assert all(s["time"] != 720 for s in r["signals"])


def test_metrics_are_consistent():
    r = run_backtest(random_bars(800, seed=3), "X", "1m", 9, 21, COSTS)
    m = r["metrics"]
    assert m["final_equity"] - 100_000 == pytest.approx(m["realized_pnl"] + m["unrealized_pnl"], abs=1e-6)
    assert m["final_equity"] == pytest.approx(r["equity"][-1]["equity"], abs=1e-3)
    assert 0 <= m["max_drawdown_pct"] < 100 and 0 <= m["exposure_pct"] <= 100
    assert m["fees"] > 0 and m["fills"] == len(r["trades"])


def test_live_bot_makes_exactly_the_backtest_trades():
    """Incremental live processing (candle events) == event-driven backtest on the same candles."""
    bars = random_bars(500, seed=21)
    bt = run_backtest(bars, "AAPL", "1m", 9, 21, COSTS)
    store = CandleStore(connect(":memory:"), {"1m": 60})
    live = LiveTrader(store, ["AAPL"], "1m", 9, 21, COSTS, now_ms=0)
    for b in bars:
        opening = {**b, "symbol": "AAPL", "interval": "1m", "is_complete": False, "close": b["open"]}
        live.on_candles([opening], b["time"] * 1000)           # first tick of the candle
        live.on_candles([{**b, "symbol": "AAPL", "interval": "1m"}], b["time"] * 1000 + 59_000)  # it completes
    fills = [dict(r) for r in store.conn.execute("SELECT * FROM sim_fills WHERE account_id='live' ORDER BY id")]
    assert [(f["fill_bar"], f["side"], round(f["fill_price"], 8), round(f["qty"], 8)) for f in fills] == \
           [(t["time"], t["side"], round(t["fill_price"], 8), round(t["qty"], 8)) for t in bt["trades"]]
    assert len(fills) > 4
