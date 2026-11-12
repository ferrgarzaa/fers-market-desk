"""Feed decoding and the unavailable-feed condition (no network needed)."""
import asyncio
import base64
import json

from yfinance.pricing_pb2 import PricingData

from app.feed import FakeFeed, YahooFeed, decode_yahoo_message, tick_from_yahoo


def yahoo_frame(**kw) -> str:
    """Build a frame exactly like Yahoo's streamer sends: JSON with base64 protobuf."""
    return json.dumps({"type": "pricing", "message": base64.b64encode(PricingData(**kw).SerializeToString()).decode()})


def test_decode_real_format_frame():
    d = decode_yahoo_message(yahoo_frame(id="BTC-USD", price=98765.43, time=1762957201000, day_volume=123456))
    t = tick_from_yahoo(d)
    assert t.symbol == "BTC-USD" and t.source_time_ms == 1762957201000
    assert abs(t.price - 98765.43) < 0.01        # float32 noise trimmed
    assert t.day_volume == 123456.0 and t.source == "yahoo_ws"


def test_seconds_timestamp_is_normalized_to_ms():
    t = tick_from_yahoo({"id": "AAPL", "price": 1.0, "time": "1762957201"})
    assert t.source_time_ms == 1762957201000


def test_incomplete_message_is_ignored():
    assert tick_from_yahoo({"id": "AAPL"}) is None


def test_unreachable_source_reports_unavailable_and_retries():
    states = []

    async def on_state(s, d):
        states.append((s, d))

    async def on_tick(t):
        pass

    async def main():
        feed = YahooFeed(["BTC-USD"], on_tick, on_state, url="ws://127.0.0.1:9/nothing-here",
                         backoff_min=0.05, backoff_max=0.1)
        task = asyncio.create_task(feed.run())
        await asyncio.sleep(0.6)
        task.cancel()
        return feed

    feed = asyncio.run(main())
    names = [s for s, _ in states]
    assert "connecting" in names and "unavailable" in names
    assert feed.reconnect_attempts >= 2
    assert any("retry" in d for s, d in states if s == "unavailable")


def test_simulated_outage_stops_data_and_recovers():
    ticks, states = [], []

    async def on_tick(t):
        ticks.append(t)

    async def on_state(s, d):
        states.append(s)

    async def main():
        feed = FakeFeed(["BTC-USD"], on_tick, on_state, period_s=0.02)
        task = asyncio.create_task(feed.run())
        await asyncio.sleep(0.1)
        await feed.set_outage(True)
        n = len(ticks)
        await asyncio.sleep(0.15)
        during = len(ticks) - n
        await feed.set_outage(False)
        await asyncio.sleep(0.1)
        task.cancel()
        return during

    during = asyncio.run(main())
    assert during <= 1
    assert "unavailable" in states and states[-1] == "live"
