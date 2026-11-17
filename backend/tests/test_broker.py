"""Simulated accounting checked against hand-computed examples."""
import random
import sqlite3

import pytest

from app.broker import BrokerConfig, SimBroker


def broker(cfg):
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    return SimBroker(c, "t", cfg)


def test_round_trip_without_costs_hand_example():
    b = broker(BrokerConfig(100_000, fee_rate=0, slippage=0, alloc=0.10))
    o = b.submit("AAPL", "BUY", signal_bar=0, signal_close=99, reason="test", created_ms=0)
    assert o["status"] == "pending"
    assert b.fill_pending("AAPL", 0, 100, 0) == []              # same bar as signal: never filled
    f = b.fill_pending("AAPL", 60, 100, 1)[0]                   # next bar open = 100
    assert f["qty"] == pytest.approx(100) and f["cash_after"] == pytest.approx(90_000)
    snap = b.snapshot({"AAPL": 105})
    assert snap["equity"] == pytest.approx(100_500) and snap["unrealized_pnl"] == pytest.approx(500)
    b.submit("AAPL", "SELL", 120, 108, "test", 2)
    f = b.fill_pending("AAPL", 180, 110, 3)[0]
    assert f["realized_pnl"] == pytest.approx(1_000)
    snap = b.snapshot({"AAPL": 110})
    assert snap["cash"] == pytest.approx(101_000) and snap["positions"] == []
    assert snap["realized_pnl"] == pytest.approx(1_000) and snap["return_pct"] == pytest.approx(1.0)


def test_round_trip_with_fee_and_slippage_hand_example():
    b = broker(BrokerConfig(100_000, fee_rate=0.001, slippage=0.0005, alloc=0.10))
    b.submit("BTC-USD", "BUY", 0, 99, "t", 0)
    f = b.fill_pending("BTC-USD", 60, 100, 0)[0]
    # buy: px = 100 * 1.0005 = 100.05 ; spend exactly 10% of cash including the fee
    assert f["fill_price"] == pytest.approx(100.05)
    assert f["qty"] == pytest.approx(10_000 / (100.05 * 1.001))          # 99.850174...
    assert f["fee"] == pytest.approx(10_000 / 1.001 * 0.001)             # 9.99001
    assert f["cash_after"] == pytest.approx(90_000)
    pos = b.position("BTC-USD")
    assert pos["avg_cost"] == pytest.approx(10_000 / pos["qty"])         # basis includes buy fee
    b.submit("BTC-USD", "SELL", 120, 109, "t", 1)
    f = b.fill_pending("BTC-USD", 180, 110, 2)[0]
    qty = 10_000 / (100.05 * 1.001)
    px = 110 * 0.9995                                                    # 109.945
    proceeds = px * qty * (1 - 0.001)
    assert f["fill_price"] == pytest.approx(px)
    assert f["realized_pnl"] == pytest.approx(proceeds - 10_000)         # ≈ +967.05
    assert f["realized_pnl"] == pytest.approx(967.0494, abs=1e-3)
    assert b.cash == pytest.approx(90_000 + proceeds)
    assert b.snapshot({})["fees"] == pytest.approx(10_000 / 1.001 * 0.001 + px * qty * 0.001)


def test_skips_are_recorded_not_silently_dropped():
    b = broker(BrokerConfig(alloc=0.1))
    assert b.submit("TSLA", "SELL", 0, 1, "t", 0)["note"].startswith("no position")
    b.submit("TSLA", "BUY", 0, 1, "t", 0)
    assert b.submit("TSLA", "BUY", 1, 1, "t", 0)["status"] == "skipped"     # pending exists
    b.fill_pending("TSLA", 60, 10, 0)
    assert "already long" in b.submit("TSLA", "BUY", 60, 1, "t", 0)["note"]
    statuses = [o["status"] for o in b.snapshot({})["orders"]]
    assert statuses.count("skipped") == 3 and statuses.count("filled") == 1


def test_accounting_identity_holds_over_random_trading():
    """equity - starting_cash == realized + unrealized, after every step."""
    rng = random.Random(5)
    cfg = BrokerConfig(100_000, 0.001, 0.0005, 0.10)
    b = broker(cfg)
    syms = ["AAPL", "TSLA", "BTC-USD"]
    px = {s: 100.0 for s in syms}
    for bar in range(1, 400):
        for s in syms:
            px[s] *= 1 + rng.gauss(0, 0.01)
            b.fill_pending(s, bar * 60, px[s], bar)
            if rng.random() < 0.15:
                b.submit(s, rng.choice(["BUY", "SELL"]), bar * 60, px[s], "random", bar)
        snap = b.snapshot(px)
        assert snap["equity"] - cfg.starting_cash == pytest.approx(
            snap["realized_pnl"] + snap["unrealized_pnl"], abs=1e-6)
        assert snap["cash"] >= 0


def test_reset_restores_starting_cash():
    b = broker(BrokerConfig())
    b.submit("AAPL", "BUY", 0, 1, "t", 0)
    b.fill_pending("AAPL", 60, 10, 0)
    b.reset(1)
    s = b.snapshot({})
    assert s["cash"] == 100_000 and s["positions"] == [] and s["orders"] == []
