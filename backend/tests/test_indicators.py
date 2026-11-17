"""SMA and crossover: trusted reference (pandas), batch vs incremental, hand examples, provisional."""
import math
import random

import pandas as pd
import pytest

from app.indicators import (CrossoverDetector, IncrementalSMA, crossover_signals, indicator_series,
                            sma_batch)


def random_walk(n, seed=1, start=100.0):
    rng = random.Random(seed)
    out, p = [], start
    for _ in range(n):
        p *= 1 + rng.gauss(0, 0.004)
        out.append(round(p, 4))
    return out


def same(a, b, tol=1e-9):
    if a is None or (isinstance(a, float) and math.isnan(a)):
        return b is None or (isinstance(b, float) and math.isnan(b))
    return b is not None and abs(a - b) <= tol * max(1.0, abs(a))


@pytest.mark.parametrize("n", [1, 2, 9, 21, 50])
def test_sma_batch_matches_pandas_rolling_mean(n):
    closes = random_walk(800, seed=n)
    ref = pd.Series(closes).rolling(n).mean().tolist()      # trusted reference implementation
    ours = sma_batch(closes, n)
    assert all(same(r, o) for r, o in zip(ref, ours))


def test_sma_hand_example():
    assert sma_batch([1, 2, 3, 4, 5], 3) == [None, None, 2.0, 3.0, 4.0]


@pytest.mark.parametrize("n", [3, 9, 21])
def test_incremental_equals_batch(n):
    closes = random_walk(2000, seed=42 + n, start=90000)
    inc = IncrementalSMA(n)
    assert all(same(b, inc.add(c)) for b, c in zip(sma_batch(closes, n), closes))


def test_peek_does_not_change_state_and_equals_next_value():
    inc = IncrementalSMA(3)
    for c in [1, 2, 3]:
        inc.add(c)
    assert inc.peek(10) == pytest.approx((2 + 3 + 10) / 3)
    assert inc.value == pytest.approx(2.0)            # unchanged
    assert inc.add(10) == pytest.approx((2 + 3 + 10) / 3)


# fast=2 / slow=4 worked example (also used in test_backtest.py and docs/STRATEGY.md)
CLOSES = [10, 10, 10, 10, 9, 8, 12, 14, 13, 9, 7, 6]


def test_crossover_hand_example():
    sig = crossover_signals(CLOSES, 2, 4)
    # diff: i3=0 (touch, no sign) i4<0 (initialises bearish) i6>0 BUY  i9<0 SELL
    assert [(i, s) for i, s in enumerate(sig) if s] == [(6, "BUY"), (9, "SELL")]


def test_touch_is_not_a_cross():
    det = CrossoverDetector(1, 2)
    # closes chosen so diff = close - mean(prev, close) = (c - prev)/2 : +,0,+  then -
    seq = [10, 11, 11, 12, 11]
    out = [det.update(c)[2] for c in seq]
    assert out == [None, None, None, None, "SELL"]   # above -> touch -> above: no BUY; then down: SELL


def test_batch_and_incremental_signals_identical_on_long_series():
    closes = random_walk(5000, seed=7)
    det = CrossoverDetector(9, 21)
    inc = [det.update(c)[2] for c in closes]
    assert inc == crossover_signals(closes, 9, 21)
    assert inc.count("BUY") > 10 and inc.count("SELL") > 10
    # signals alternate (cannot BUY twice without a SELL between)
    seq = [s for s in inc if s]
    assert all(a != b for a, b in zip(seq, seq[1:]))


def test_indicator_series_flags_provisional_last_candle():
    closes = random_walk(40, seed=3)
    candles = [{"time": 60 * i, "close": c, "is_complete": True} for i, c in enumerate(closes)]
    candles[-1]["is_complete"] = False                   # the forming candle
    ind = indicator_series(candles, 9, 21)
    pts = ind["points"]
    assert len(pts) == 40 and pts[-1]["provisional"] and not pts[-2]["provisional"]
    # provisional point equals the batch value computed as if the candle had closed now
    assert pts[-1]["fast"] == pytest.approx(sma_batch(closes, 9)[-1])
    assert pts[-1]["slow"] == pytest.approx(sma_batch(closes, 21)[-1])
    # confirmed points are computed from completed candles only
    assert pts[-2]["slow"] == pytest.approx(sma_batch(closes[:-1], 21)[-1])


def test_rejects_bad_windows():
    with pytest.raises(ValueError):
        CrossoverDetector(21, 9)
    with pytest.raises(ValueError):
        sma_batch([1, 2], 0)
