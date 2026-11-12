"""Unit tests for observation identity, duplicates, revisions, out-of-order and completion."""
import pytest

from app.db import connect
from app.store import Bar, CandleStore, Tick

IV = {"1m": 60, "5m": 300}
T0 = 1_762_957_200_000  # 2025-11-12 14:20:00 UTC, aligned to 1m and 5m buckets


@pytest.fixture
def store():
    return CandleStore(connect(":memory:"), IV, grace_s=3)


def tick(price, t_ms, vol=None, sym="BTC-USD"):
    return Tick(symbol=sym, price=price, source_time_ms=t_ms, day_volume=vol)


def candle(store, iv="1m", sym="BTC-USD"):
    return store.get_candles(sym, iv)


def test_first_tick_opens_provisional_candle(store):
    r = store.ingest_tick(tick(100.0, T0 + 1000), received_ms=T0 + 1100)
    assert r["status"] == "accepted" and r["arrival"] == "in_order"
    c = candle(store)[0]
    assert (c["open"], c["high"], c["low"], c["close"]) == (100.0, 100.0, 100.0, 100.0)
    assert c["is_complete"] is False and c["revision"] == 1
    assert c["time"] == T0 // 1000


def test_exact_duplicate_is_rejected_and_changes_nothing(store):
    store.ingest_tick(tick(100.0, T0 + 1000, vol=10), T0 + 1100)
    before = candle(store)[0]
    r = store.ingest_tick(tick(100.0, T0 + 1000, vol=10), T0 + 1200)
    assert r["status"] == "duplicate"
    assert candle(store)[0] == before
    s = store.stats()
    assert s["duplicates"] == 1 and s["ticks"] == 1


def test_same_time_different_price_is_not_a_duplicate(store):
    store.ingest_tick(tick(100.0, T0 + 1000), T0 + 1100)
    r = store.ingest_tick(tick(101.0, T0 + 1000), T0 + 1200)
    assert r["status"] == "accepted"
    assert candle(store)[0]["close"] == 101.0


def test_revisions_are_recorded_for_every_change(store):
    store.ingest_tick(tick(100.0, T0 + 1000, vol=0), T0 + 1001)
    store.ingest_tick(tick(105.0, T0 + 2000, vol=5), T0 + 2001)
    store.ingest_tick(tick(98.0, T0 + 3000, vol=12), T0 + 3001)
    c = candle(store)[0]
    assert (c["open"], c["high"], c["low"], c["close"], c["volume"]) == (100.0, 105.0, 98.0, 98.0, 12.0)
    assert c["revision"] == 3
    revs = store.get_revisions("BTC-USD", "1m", T0 // 1000)
    assert [r["revision"] for r in revs] == [1, 2, 3]
    assert [r["close"] for r in revs] == [100.0, 105.0, 98.0]
    assert [r["reason"] for r in revs] == ["open", "tick", "tick"]


def test_unchanged_tick_does_not_create_revision(store):
    store.ingest_tick(tick(100.0, T0 + 1000), T0 + 1001)
    store.ingest_tick(tick(100.0, T0 + 2000), T0 + 2001)  # same price, newer time, no volume
    c = candle(store)[0]
    assert c["revision"] == 1 and c["tick_count"] == 2


def test_out_of_order_tick_widens_range_but_never_replaces_close(store):
    store.ingest_tick(tick(100.0, T0 + 1000, vol=0), T0 + 1001)
    store.ingest_tick(tick(102.0, T0 + 5000, vol=10), T0 + 5001)
    r = store.ingest_tick(tick(90.0, T0 + 3000, vol=7), T0 + 6000)  # arrives late, older source time
    assert r["arrival"] == "out_of_order"
    c = candle(store)[0]
    assert c["low"] == 90.0          # range widened
    assert c["close"] == 102.0       # close still belongs to the newest source time
    assert c["volume"] == 10.0       # stale cumulative counter contributes no volume
    assert store.stats()["out_of_order"] == 1
    assert store.get_revisions("BTC-USD", "1m", T0 // 1000)[-1]["reason"] == "out_of_order"


def test_out_of_order_tick_earlier_than_first_becomes_open(store):
    store.ingest_tick(tick(100.0, T0 + 20000), T0 + 20001)
    store.ingest_tick(tick(101.0, T0 + 30000), T0 + 30001)
    store.ingest_tick(tick(99.5, T0 + 5000), T0 + 31000)
    c = candle(store)[0]
    assert c["open"] == 99.5 and c["close"] == 101.0


def test_new_bucket_finalizes_previous_candle(store):
    store.ingest_tick(tick(100.0, T0 + 1000), T0 + 1001)
    r = store.ingest_tick(tick(101.0, T0 + 61000), T0 + 61001)
    cs = candle(store)
    assert len(cs) == 2
    assert cs[0]["is_complete"] is True and cs[1]["is_complete"] is False
    assert any(c["reason"] == "finalize" and c["interval"] == "1m" for c in r["candles"])
    # the 5m candle is still the same provisional bucket
    assert len(candle(store, "5m")) == 1 and candle(store, "5m")[0]["is_complete"] is False


def test_clock_finalizes_after_interval_plus_grace(store):
    store.ingest_tick(tick(100.0, T0 + 1000), T0 + 1001)
    assert store.finalize_due(T0 + 60_000 + 2_000) == []          # still inside grace
    done = store.finalize_due(T0 + 60_000 + 3_000)
    assert [d["interval"] for d in done] == ["1m"]
    assert candle(store)[0]["is_complete"] is True


def test_late_tick_revises_completed_candle_and_keeps_it_complete(store):
    store.ingest_tick(tick(100.0, T0 + 1000), T0 + 1001)
    store.ingest_tick(tick(101.0, T0 + 61000), T0 + 61001)   # finalizes the first minute
    store.ingest_tick(tick(120.0, T0 + 59000), T0 + 62000)   # late, belongs to first minute
    first = candle(store)[0]
    # newest source time *within that bucket* -> it becomes that bucket's close; candle stays complete
    assert first["is_complete"] is True and first["high"] == 120.0 and first["close"] == 120.0
    assert store.get_revisions("BTC-USD", "1m", T0 // 1000)[-1]["reason"] == "late"
    assert store.stats()["late_revisions"] >= 1


def test_volume_from_cumulative_counter_and_reset(store):
    store.ingest_tick(tick(100.0, T0 + 1000, vol=1000), T0 + 1001)   # first: no delta known
    store.ingest_tick(tick(100.5, T0 + 2000, vol=1040), T0 + 2001)   # +40
    store.ingest_tick(tick(100.6, T0 + 3000, vol=5), T0 + 3001)      # counter reset -> 0
    store.ingest_tick(tick(100.7, T0 + 4000, vol=25), T0 + 4001)     # +20
    assert candle(store)[0]["volume"] == 60.0


def test_history_bar_then_live_ticks_revise_it(store):
    b = Bar("BTC-USD", "1m", T0 // 1000, 100, 101, 99, 100.5, 7.0)
    store.ingest_bar(b, received_ms=T0 + 10_000, now_ms=T0 + 10_000)
    c = candle(store)[0]
    assert c["source"] == "yahoo_history" and c["is_complete"] is False
    store.ingest_tick(tick(103.0, T0 + 20_000), T0 + 20_001)
    c = candle(store)[0]
    assert c["high"] == 103.0 and c["close"] == 103.0 and c["revision"] == 2
    # identical bar re-sent on the next backfill is a duplicate
    assert store.ingest_bar(b, T0 + 30_000)["status"] == "duplicate"


def test_history_never_overwrites_live_built_candle(store):
    store.ingest_tick(tick(100.0, T0 + 1000), T0 + 1001)
    store.ingest_bar(Bar("BTC-USD", "1m", T0 // 1000, 1, 1, 1, 1, 1), T0 + 2000)
    assert candle(store)[0]["close"] == 100.0
    assert store.stats()["history_conflicts_kept_live"] == 1


def test_replay_returns_revisions_in_recorded_order(store):
    for i, p in enumerate([100, 101, 102, 103]):
        store.ingest_tick(tick(float(p), T0 + 1000 + i * 1000), T0 + 1001 + i * 1000)
    rep = store.get_replay("BTC-USD", "1m")
    assert [r["close"] for r in rep] == [100, 101, 102, 103]
    assert rep == sorted(rep, key=lambda r: r["id"])


def test_out_of_order_detection_survives_restart(tmp_path):
    path = tmp_path / "m.db"
    s1 = CandleStore(connect(path), IV)
    s1.ingest_tick(tick(100.0, T0 + 5000), T0 + 5001)
    s1.conn.close()
    s2 = CandleStore(connect(path), IV)
    assert s2.ingest_tick(tick(99.0, T0 + 1000), T0 + 6000)["arrival"] == "out_of_order"
