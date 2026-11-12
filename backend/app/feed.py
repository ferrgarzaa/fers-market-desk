"""Market-data feeds.

YahooFeed  – the live, graded path. Connects to Yahoo Finance's streaming
             WebSocket, subscribes to the symbols, and decodes each base64
             protobuf message with yfinance's own `PricingData` schema.
             We manage the socket ourselves (instead of yfinance's
             AsyncWebSocket.listen loop) so the application can observe and
             report every connection state: connecting / connected / live /
             stale / unavailable, plus reconnect attempts and the error text.
FakeFeed   – deterministic random-walk ticks, ONLY for automated tests and
             offline UI work (FEED_MODE=fake). Labelled "FAKE" everywhere.

History backfill (recent bars) comes from yfinance's Ticker.history over HTTP.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import random
import time
from typing import Awaitable, Callable, Optional

from .store import Bar, Tick

log = logging.getLogger("feed")


def now_ms() -> int:
    return int(time.time() * 1000)


def decode_yahoo_message(raw: str) -> dict:
    """Decode one Yahoo streamer frame: JSON {"message": base64(protobuf)} -> dict."""
    from google.protobuf.json_format import MessageToDict
    from yfinance.pricing_pb2 import PricingData

    payload = json.loads(raw).get("message", "")
    pd = PricingData()
    pd.ParseFromString(base64.b64decode(payload))
    return MessageToDict(pd, preserving_proto_field_name=True)


def tick_from_yahoo(d: dict) -> Optional[Tick]:
    """Convert a decoded PricingData dict into a Tick. Returns None if unusable."""
    sym = d.get("id")
    price = d.get("price")
    t = d.get("time")
    if not sym or price is None or t is None:
        return None
    t = int(t)
    if t < 10**12:          # some frames carry seconds instead of milliseconds
        t *= 1000
    # price is a protobuf float32; trim the float32 noise to 7 significant digits
    price = float(f"{float(price):.7g}")
    vol = d.get("day_volume", d.get("vol_24hr"))
    return Tick(symbol=sym, price=price, source_time_ms=t, source="yahoo_ws",
                day_volume=float(vol) if vol is not None else None,
                market_hours=d.get("market_hours"), raw=d)


TickHandler = Callable[[Tick], Awaitable[None]]
StateHandler = Callable[[str, str], Awaitable[None]]


class BaseFeed:
    name = "base"
    source_label = "?"

    def __init__(self, symbols: list[str], on_tick: TickHandler, on_state: StateHandler):
        self.symbols = symbols
        self.on_tick = on_tick
        self.on_state = on_state
        self.state = "starting"
        self.detail = ""
        self.last_message_ms: Optional[int] = None
        self.connected_since_ms: Optional[int] = None
        self.reconnect_attempts = 0
        self.messages = 0
        self.simulated_outage = False
        self._outage_cleared = asyncio.Event()
        self._outage_cleared.set()

    async def set_state(self, state: str, detail: str = ""):
        if state != self.state or detail != self.detail:
            self.state, self.detail = state, detail
            await self.on_state(state, detail)

    async def set_outage(self, enabled: bool):
        self.simulated_outage = enabled
        if enabled:
            self._outage_cleared.clear()
            await self._drop_connection()
            await self.set_state("unavailable", "Simulated outage (operator toggle) – no data is arriving")
        else:
            self._outage_cleared.set()

    async def _drop_connection(self):
        pass

    def snapshot(self) -> dict:
        return {"mode": self.name, "source": self.source_label, "state": self.state, "detail": self.detail,
                "last_message_ms": self.last_message_ms, "connected_since_ms": self.connected_since_ms,
                "reconnect_attempts": self.reconnect_attempts, "messages": self.messages,
                "simulated_outage": self.simulated_outage}

    async def _handle(self, tick: Tick):
        self.messages += 1
        self.last_message_ms = now_ms()
        if self.state != "live":
            await self.set_state("live", f"receiving {self.source_label} messages")
        await self.on_tick(tick)


class YahooFeed(BaseFeed):
    name = "yahoo"
    source_label = "Yahoo Finance WebSocket"

    def __init__(self, symbols, on_tick, on_state, url: str, backoff_min=2.0, backoff_max=30.0):
        super().__init__(symbols, on_tick, on_state)
        self.url = url
        self.backoff_min, self.backoff_max = backoff_min, backoff_max
        self._ws = None

    async def _drop_connection(self):
        if self._ws is not None:
            try:
                await self._ws.close()
            except Exception:
                pass

    async def _heartbeat(self, ws):
        # Yahoo stops sending if the subscription is not refreshed (yfinance does the same).
        while True:
            await asyncio.sleep(15)
            await ws.send(json.dumps({"subscribe": self.symbols}))

    async def run(self):
        import websockets

        backoff = self.backoff_min
        while True:
            if self.simulated_outage:
                await self._outage_cleared.wait()
                continue
            await self.set_state("connecting", self.url)
            hb = None
            try:
                async with websockets.connect(self.url, open_timeout=10, ping_interval=20,
                                              ping_timeout=20) as ws:
                    self._ws = ws
                    self.connected_since_ms = now_ms()
                    await ws.send(json.dumps({"subscribe": self.symbols}))
                    await self.set_state("connected", "subscribed, waiting for first message")
                    hb = asyncio.create_task(self._heartbeat(ws))
                    async for raw in ws:
                        try:
                            tick = tick_from_yahoo(decode_yahoo_message(raw))
                        except Exception as e:  # malformed frame: log and keep going
                            log.warning("could not decode frame: %s", e)
                            continue
                        if tick and tick.symbol in self.symbols:
                            backoff = self.backoff_min
                            self.reconnect_attempts = 0
                            await self._handle(tick)
                if not self.simulated_outage:
                    raise ConnectionError("stream closed by server")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                if self.simulated_outage:
                    continue
                self.reconnect_attempts += 1
                self.connected_since_ms = None
                await self.set_state(
                    "unavailable",
                    f"{type(e).__name__}: {e} – retry #{self.reconnect_attempts} in {backoff:.0f}s")
                await asyncio.sleep(backoff)
                backoff = min(backoff * 2, self.backoff_max)
            finally:
                if hb:
                    hb.cancel()
                self._ws = None


class FakeFeed(BaseFeed):
    """Synthetic ticks for tests/offline only. Never used for the graded live demo."""
    name = "fake"
    source_label = "FAKE synthetic feed (tests only)"

    START = {"BTC-USD": 90000.0, "ETH-USD": 3200.0, "AAPL": 230.0, "TSLA": 330.0, "NVDA": 190.0}

    def __init__(self, symbols, on_tick, on_state, period_s: float = 0.5, seed: int = 7):
        super().__init__(symbols, on_tick, on_state)
        self.period_s = period_s
        self.rng = random.Random(seed)
        self.prices = {s: self.START.get(s, 100.0) for s in symbols}
        self.cum = {s: 0.0 for s in symbols}

    async def run(self):
        self.connected_since_ms = now_ms()
        while True:
            if self.simulated_outage:
                await self._outage_cleared.wait()
                continue
            for s in self.symbols:
                self.prices[s] *= 1 + self.rng.gauss(0, 0.0008)
                self.cum[s] += self.rng.randint(1, 50)
                await self._handle(Tick(symbol=s, price=round(self.prices[s], 4), source_time_ms=now_ms(),
                                        source="fake", day_volume=self.cum[s]))
            await asyncio.sleep(self.period_s)


def fake_history(symbol: str, interval: str, secs: int, count: int = 120, seed: int = 3) -> list[Bar]:
    rng = random.Random(f"{symbol}{interval}{seed}")
    p = FakeFeed.START.get(symbol, 100.0)
    end = (int(time.time()) // secs) * secs  # current (incomplete) bucket is left to the live feed
    bars = []
    for i in range(count, 0, -1):
        start = end - i * secs
        o = p
        c = o * (1 + rng.gauss(0, 0.002))
        h, l = max(o, c) * (1 + abs(rng.gauss(0, 0.001))), min(o, c) * (1 - abs(rng.gauss(0, 0.001)))
        bars.append(Bar(symbol, interval, start, round(o, 4), round(h, 4), round(l, 4), round(c, 4),
                        float(rng.randint(100, 3000)), source="fake_history"))
        p = c
    return bars


HISTORY_PERIOD = {"1m": "1d", "5m": "5d", "15m": "5d"}


def yahoo_history(symbol: str, interval: str, limit: int = 400) -> list[Bar]:
    """Blocking call (run it in a thread). Recent bars from yfinance's HTTP history API."""
    import yfinance as yf

    df = yf.Ticker(symbol).history(period=HISTORY_PERIOD[interval], interval=interval,
                                   auto_adjust=False, prepost=False)
    bars = []
    for ts, row in df.tail(limit).iterrows():
        bars.append(Bar(symbol, interval, int(ts.timestamp()), float(row["Open"]), float(row["High"]),
                        float(row["Low"]), float(row["Close"]), float(row["Volume"]),
                        source="yahoo_history"))
    return bars
