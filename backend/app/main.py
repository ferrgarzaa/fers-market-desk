"""FastAPI application: REST endpoints + one WebSocket (/ws) for the browser.

Data path:  Yahoo WS -> YahooFeed -> CandleStore (SQLite) -> Hub -> browser WebSocket -> chart
Part 4.2:   completed candles -> LiveTrader (SMA crossover) -> SimBroker (SQLite) -> account panel
            stored completed candles -> run_backtest (event-driven) -> backtest panel
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
from .backtest import run_backtest, save_run
from .broker import BrokerConfig
from .indicators import indicator_series
from .store import CandleStore, Tick
from .trader import LiveTrader

log = logging.getLogger("app")
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")


class OutageBody(BaseModel):
    enabled: bool


class BacktestBody(BaseModel):
    symbol: str
    interval: str = "1m"
    fast: int = config.SMA_FAST
    slow: int = config.SMA_SLOW


def broker_config() -> BrokerConfig:
    return BrokerConfig(config.STARTING_CASH, config.FEE_RATE, config.SLIPPAGE, config.ALLOC)


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
        self.trader = LiveTrader(self.store, config.SYMBOLS, config.STRATEGY_INTERVAL,
                                 config.SMA_FAST, config.SMA_SLOW, broker_config(), now_ms())

    # ---------------------------------------------------------------- lifecycle
    async def start(self):
        self.store.record_feed_event(now_ms(), "startup", f"feed mode={self.feed_mode}")
        self.trader.prime()
        # The live stream starts immediately; history loads in parallel and is merged by the store
        # (a live-built candle always wins over a history bar for the same bucket).
        self.tasks = [asyncio.create_task(self.feed.run(), name="feed"),
                      asyncio.create_task(self.clock_loop(), name="clock")]
        if config.BACKFILL:
            if self.feed_mode == "fake":
                await self.backfill()
                self.trader.prime()
            else:
                self.tasks.append(asyncio.create_task(self.backfill_then_refresh(), name="backfill"))

    async def backfill_then_refresh(self):
        await self.backfill()
        self.trader.prime()  # SMAs now also cover the backfilled history
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
                        bars = await asyncio.wait_for(asyncio.to_thread(yahoo_history, sym, iv), 30)
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
        await self.trade(res["candles"], received)
        await self.push_candles(tick.symbol, res["candles"])

    async def trade(self, candles: list[dict], t: int):
        """Feed candle revisions to the live bot and announce any order or fill."""
        ev = self.trader.on_candles(candles, t)
        for o in ev["orders"]:
            await self.broadcast({"type": "order", "order": o})
        for f in ev["fills"]:
            await self.broadcast({"type": "fill", "fill": f})

    def indicator_tail(self, symbol: str, interval: str, n: int = 3) -> dict:
        cs = self.store.get_candles(symbol, interval, limit=config.SMA_SLOW + 80)
        ind = indicator_series(cs, config.SMA_FAST, config.SMA_SLOW)
        ind["points"] = ind["points"][-n:]
        return ind

    async def push_candles(self, symbol: str, candles: list[dict]):
        pairs = set()
        for c in candles:
            for cl in list(self.clients):
                if cl.symbol == symbol and cl.interval == c["interval"] and cl.replay_task is None:
                    await self._safe_send(cl, {"type": "candle", "candle": c})
                    pairs.add((cl, c["interval"]))
        tails: dict[str, dict] = {}
        for cl, iv in pairs:
            if iv not in tails:
                tails[iv] = self.indicator_tail(symbol, iv)
            await self._safe_send(cl, {"type": "indicators_tail", "symbol": symbol, "interval": iv,
                                       "indicators": tails[iv]})

    async def clock_loop(self):
        """Every second: finalize candles whose interval ended, detect stale feed, push status."""
        while True:
            await asyncio.sleep(1)
            done = self.store.finalize_due(now_ms())
            if done:
                await self.trade(done, now_ms())
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
                "history": self.history_state, "db": self.store.stats(), "db_path": str(self.db_path),
                "account": self.trader.broker.snapshot(self.marks()),
                "strategy": {s: self.trader.strategy_status(s) for s in config.SYMBOLS}}

    def marks(self) -> dict[str, float]:
        """Mark-to-market prices: the latest tick, else the latest stored close."""
        out = {}
        for s in config.SYMBOLS:
            if s in self.last_tick:
                out[s] = self.last_tick[s]["price"]
            else:
                cs = self.store.get_candles(s, config.STRATEGY_INTERVAL, limit=1)
                if cs:
                    out[s] = cs[-1]["close"]
        return out

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
        candles = self.store.get_candles(cl.symbol, cl.interval)
        await cl.send({"type": "snapshot", "symbol": cl.symbol, "interval": cl.interval, "candles": candles,
                       "indicators": indicator_series(candles, config.SMA_FAST, config.SMA_SLOW)})
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

    # ---------------------------------------------------------------- Part 4.2
    @app.get("/api/indicators")
    def indicators(symbol: str, interval: str = "1m", limit: int = 500, fast: int = config.SMA_FAST,
                   slow: int = config.SMA_SLOW):
        check_pair(symbol, interval)
        if not 1 <= fast < slow <= 500:
            raise HTTPException(400, "need 1 <= fast < slow <= 500")
        return indicator_series(hub().store.get_candles(symbol, interval, min(limit, 5000)), fast, slow)

    @app.get("/api/account")
    def account():
        h = hub()
        return h.trader.broker.snapshot(h.marks(), limit=200)

    @app.post("/api/account/reset")
    async def account_reset():
        h = hub()
        h.trader.broker.reset(now_ms())
        h.trader.last_signal.clear()
        await h.broadcast_status()
        return h.trader.broker.snapshot(h.marks())

    @app.post("/api/backtest")
    def backtest(body: BacktestBody):
        check_pair(body.symbol, body.interval)
        if not 1 <= body.fast < body.slow <= 500:
            raise HTTPException(400, "need 1 <= fast < slow <= 500")
        h = hub()
        candles = h.store.get_candles(body.symbol, body.interval, limit=5000)
        complete = [c for c in candles if c["is_complete"]]
        if len(complete) < body.slow + 2:
            raise HTTPException(409, f"only {len(complete)} completed candles stored; need at least {body.slow + 2}")
        result = run_backtest(complete, body.symbol, body.interval, body.fast, body.slow, broker_config())
        result["run_id"] = save_run(h.conn, result, now_ms())
        result["excluded_provisional"] = len(candles) - len(complete)
        return result

    @app.get("/api/backtests")
    def backtests(limit: int = 20):
        rows = hub().conn.execute(
            "SELECT id, created_ms, symbol, interval, fast, slow, bars, metrics_json FROM backtest_runs "
            "ORDER BY id DESC LIMIT ?", (min(limit, 200),)).fetchall()
        import json as _json
        return [{**{k: r[k] for k in ("id", "created_ms", "symbol", "interval", "fast", "slow", "bars")},
                 "metrics": _json.loads(r["metrics_json"])} for r in rows]

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
