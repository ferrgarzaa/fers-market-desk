"""FastAPI application: REST endpoints + one WebSocket (/ws) for the browser.

Data path:  Yahoo WS -> YahooFeed -> CandleStore (SQLite) -> Hub -> browser WebSocket -> chart
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
from typing import Optional

from fastapi import FastAPI, HTTPException, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from . import config
from .db import connect
from .feed import FakeFeed, YahooFeed, fake_history, now_ms, yahoo_history
from .store import CandleStore, Tick

log = logging.getLogger("app")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class OutageBody(BaseModel):
    enabled: bool


class Client:
    def __init__(self, ws: WebSocket):
        self.ws = ws
        self.symbol = config.SYMBOLS[0]
        self.interval = "1m"
        self.replay_task: Optional[asyncio.Task] = None
        self.lock = asyncio.Lock()

    async def send(self, msg: dict):
        async with self.lock:
            await self.ws.send_json(msg)


class Hub:
    """Owns the store, the feed and the connected browsers."""

    def __init__(self, db_path, feed_mode: str):
        self.db_path = db_path
        self.conn = connect(db_path)
        self.store = CandleStore(self.conn, config.INTERVALS, config.FINALIZE_GRACE_S)
        self.clients: set[Client] = set()
        self.last_tick: dict[str, dict] = {}
        self.history_state: dict[str, str] = {}
        self.feed_mode = feed_mode
        if feed_mode == "fake":
            self.feed = FakeFeed(config.SYMBOLS, self.on_tick, self.on_state)
        else:
            self.feed = YahooFeed(config.SYMBOLS, self.on_tick, self.on_state, config.YAHOO_WS_URL,
                                  config.RECONNECT_MIN_S, config.RECONNECT_MAX_S)
        self.tasks: list[asyncio.Task] = []

    # ---------------------------------------------------------------- lifecycle
    async def start(self):
        self.store.record_feed_event(now_ms(), "startup", f"feed mode={self.feed_mode}")
        # The live stream starts immediately; history loads in parallel and is merged by the store
        # (a live-built candle always wins over a history bar for the same bucket).
        self.tasks = [asyncio.create_task(self.feed.run(), name="feed"),
                      asyncio.create_task(self.clock_loop(), name="clock")]
        if config.BACKFILL:
            if self.feed_mode == "fake":
                await self.backfill()
            else:
                self.tasks.append(asyncio.create_task(self.backfill_then_refresh(), name="backfill"))

    async def backfill_then_refresh(self):
        await self.backfill()
        for cl in list(self.clients):
            if cl.replay_task is None:
                with contextlib.suppress(Exception):
                    await self.send_snapshot(cl)

    async def stop(self):
        for t in self.tasks:
            t.cancel()
        for t in self.tasks:
            with contextlib.suppress(asyncio.CancelledError, Exception):
                await t
        self.conn.close()

    async def backfill(self):
        for sym in config.SYMBOLS:
            for iv, secs in config.INTERVALS.items():
                try:
                    if self.feed_mode == "fake":
                        bars = fake_history(sym, iv, secs)
                    else:
                        bars = await asyncio.wait_for(asyncio.to_thread(yahoo_history, sym, iv), 20)
                    t = now_ms()
                    for b in bars:
                        self.store.ingest_bar(b, t)
                    self.history_state[f"{sym}|{iv}"] = f"ok ({len(bars)} bars)"
                except Exception as e:
                    msg = f"history unavailable for {sym} {iv}: {type(e).__name__}: {e}"
                    log.warning(msg)
                    self.history_state[f"{sym}|{iv}"] = "unavailable"
                    self.store.record_feed_event(now_ms(), "history_unavailable", msg[:300])

    # ---------------------------------------------------------------- feed callbacks
    async def on_state(self, state: str, detail: str):
        t = now_ms()
        self.store.record_feed_event(t, state, detail[:300])
        await self.broadcast({"type": "feed_event", "event": {"time_ms": t, "state": state, "detail": detail}})
        await self.broadcast_status()

    async def on_tick(self, tick: Tick):
        received = now_ms()
        res = self.store.ingest_tick(tick, received)
        self.last_tick[tick.symbol] = {
            "symbol": tick.symbol, "price": tick.price, "source_time_ms": tick.source_time_ms,
            "received_ms": received, "change_percent": tick.raw.get("change_percent"),
            "market_hours": tick.market_hours, "status": res["status"], "arrival": res["arrival"]}
        await self.broadcast({"type": "tick", "tick": self.last_tick[tick.symbol]})
        await self.push_candles(tick.symbol, res["candles"])

    async def push_candles(self, symbol: str, candles: list[dict]):
        for c in candles:
            for cl in list(self.clients):
                if cl.symbol == symbol and cl.interval == c["interval"] and cl.replay_task is None:
                    await self._safe_send(cl, {"type": "candle", "candle": c})

    async def clock_loop(self):
        """Every second: finalize candles whose interval ended, detect stale feed, push status."""
        while True:
            await asyncio.sleep(1)
            done = self.store.finalize_due(now_ms())
            by_symbol: dict[str, list] = {}
            for c in done:
                by_symbol.setdefault(c["symbol"], []).append(c)
            for s, cs in by_symbol.items():
                await self.push_candles(s, cs)
            f = self.feed
            if f.state in ("live", "connected") and not f.simulated_outage:
                ref = f.last_message_ms or f.connected_since_ms or now_ms()
                if now_ms() - ref > config.STALE_AFTER_S * 1000:
                    await f.set_state("stale", f"connected, but no message for >{config.STALE_AFTER_S:.0f}s "
                                               "(market closed or source quiet)")
            await self.broadcast_status()

    # ---------------------------------------------------------------- outbound
    def status(self) -> dict:
        return {"server_now_ms": now_ms(), "feed": self.feed.snapshot(), "symbols": config.SYMBOLS,
                "intervals": list(config.INTERVALS), "last_tick": self.last_tick,
                "history": self.history_state, "db": self.store.stats(), "db_path": str(self.db_path)}

    async def broadcast_status(self):
        await self.broadcast({"type": "status", "status": self.status()})

    async def broadcast(self, msg: dict):
        for cl in list(self.clients):
            await self._safe_send(cl, msg)

    async def _safe_send(self, cl: Client, msg: dict):
        try:
            await cl.send(msg)
        except Exception:
            self.clients.discard(cl)

    async def send_snapshot(self, cl: Client):
        await cl.send({"type": "snapshot", "symbol": cl.symbol, "interval": cl.interval,
                       "candles": self.store.get_candles(cl.symbol, cl.interval)})
        await cl.send({"type": "events", "events": self.store.recent_feed_events(30)})
        await cl.send({"type": "observations", "rows": self.store.recent_observations(cl.symbol, 20)})
        await cl.send({"type": "status", "status": self.status()})

    async def replay(self, cl: Client, speed: float):
        """Re-send the stored candle revisions for the client's pair, in the order they were recorded."""
        rows = self.store.get_replay(cl.symbol, cl.interval, limit=1500)
        await cl.send({"type": "replay_start", "symbol": cl.symbol, "interval": cl.interval, "count": len(rows)})
        delay = 1.0 / max(1.0, speed)
        try:
            for i, r in enumerate(rows):
                await cl.send({"type": "replay_candle", "index": i, "count": len(rows), "candle": r})
                await asyncio.sleep(delay)
            await cl.send({"type": "replay_done", "count": len(rows)})
        finally:
            cl.replay_task = None


def create_app(db_path=None, feed_mode=None, start_feed: bool = True) -> FastAPI:
    db_path = db_path or config.DB_PATH
    feed_mode = feed_mode or config.FEED_MODE

    @contextlib.asynccontextmanager
    async def lifespan(app: FastAPI):
        hub = Hub(db_path, feed_mode)
        app.state.hub = hub
        if start_feed:
            await hub.start()
        yield
        await hub.stop()

    app = FastAPI(title="Fer's Market Desk API", lifespan=lifespan)
    app.add_middleware(CORSMiddleware, allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
                       allow_methods=["*"], allow_headers=["*"])

    def hub(app_=None) -> Hub:
        return app.state.hub

    def check_pair(symbol: str, interval: str):
        if symbol not in config.SYMBOLS:
            raise HTTPException(404, f"unknown symbol {symbol}")
        if interval not in config.INTERVALS:
            raise HTTPException(400, f"interval must be one of {list(config.INTERVALS)}")

    @app.get("/api/health")
    def health():
        return {"ok": True, "feed_mode": feed_mode}

    @app.get("/api/status")
    def status():
        return hub().status()

    @app.get("/api/candles")
    def candles(symbol: str, interval: str = "1m", limit: int = 500):
        check_pair(symbol, interval)
        return hub().store.get_candles(symbol, interval, min(limit, 2000))

    @app.get("/api/replay")
    def replay(symbol: str, interval: str = "1m", limit: int = 1500):
        check_pair(symbol, interval)
        return hub().store.get_replay(symbol, interval, min(limit, 5000))

    @app.get("/api/revisions")
    def revisions(symbol: str, interval: str, bucket: int):
        check_pair(symbol, interval)
        return hub().store.get_revisions(symbol, interval, bucket)

    @app.get("/api/observations")
    def observations(symbol: Optional[str] = None, limit: int = 50):
        return hub().store.recent_observations(symbol, min(limit, 500))

    @app.get("/api/feed-events")
    def feed_events(limit: int = 50):
        return hub().store.recent_feed_events(min(limit, 500))

    @app.post("/api/feed/outage")
    async def outage(body: OutageBody):
        """Demonstrate the unavailable-feed condition on demand (and recover from it)."""
        await hub().feed.set_outage(body.enabled)
        return hub().feed.snapshot()

    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        await ws.accept()
        h = hub()
        cl = Client(ws)
        h.clients.add(cl)
        try:
            await h.send_snapshot(cl)
            while True:
                msg = await ws.receive_json()
                action = msg.get("action")
                if action == "subscribe":
                    sym, iv = msg.get("symbol", cl.symbol), msg.get("interval", cl.interval)
                    if sym in config.SYMBOLS and iv in config.INTERVALS:
                        if cl.replay_task:
                            cl.replay_task.cancel()
                            cl.replay_task = None
                        cl.symbol, cl.interval = sym, iv
                        await h.send_snapshot(cl)
                    else:
                        await cl.send({"type": "error", "error": f"bad subscription {sym} {iv}"})
                elif action == "replay":
                    if cl.replay_task is None:
                        cl.replay_task = asyncio.create_task(h.replay(cl, float(msg.get("speed", 40))))
                elif action == "stop_replay":
                    if cl.replay_task:
                        cl.replay_task.cancel()
                        cl.replay_task = None
                    await h.send_snapshot(cl)
                elif action == "observations":
                    await cl.send({"type": "observations",
                                   "rows": h.store.recent_observations(cl.symbol, 20)})
        except WebSocketDisconnect:
            pass
        finally:
            if cl.replay_task:
                cl.replay_task.cancel()
            h.clients.discard(cl)

    return app


app = create_app()
