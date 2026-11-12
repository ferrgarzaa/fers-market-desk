"""CandleStore: turns raw observations into candles and persists everything.

Rules (also documented in docs/DATA_FLOW.md):

* Identity / duplicates – every observation gets an `obs_key`
  (source|symbol|source_time|price|cumulative volume for ticks; the full OHLCV
  for bars). The key is UNIQUE in SQLite, so an identical re-sent message is
  rejected, counted in `ingest_counters.duplicates`, and changes nothing.
* Revisions – a candle is never overwritten silently. Every change in O/H/L/C/V
  or completeness bumps `revision` and appends a row to `candle_revisions`
  with the reason and the observation that caused it.
* Out-of-order – a tick whose source time is older than the newest tick
  already seen for that symbol is stored with arrival='out_of_order'. It can
  widen high/low, and it becomes the open if it is earlier than the candle's
  first tick, but it never replaces the close (the close always belongs to the
  latest source time). It contributes no volume, because volume is derived from
  differences of the source's cumulative counter and a stale counter would
  produce a negative or double-counted delta.
* Late ticks – a tick that lands in a candle already marked complete still
  revises it (reason='late'); the candle stays complete.
* Completion – a candle becomes complete when (a) a tick for a later bucket of
  the same symbol/interval arrives, or (b) the wall clock passes the end of the
  interval plus a grace period (`finalize_due`). Until then it is PROVISIONAL.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass, field
from typing import Optional


@dataclass
class Tick:
    symbol: str
    price: float
    source_time_ms: int
    source: str = "yahoo_ws"
    day_volume: Optional[float] = None
    market_hours: Optional[int] = None
    raw: dict = field(default_factory=dict)


@dataclass
class Bar:
    symbol: str
    interval: str
    start: int            # epoch seconds
    open: float
    high: float
    low: float
    close: float
    volume: float
    source: str = "yahoo_history"


def _candle_dict(row) -> dict:
    return {
        "symbol": row["symbol"], "interval": row["interval"], "time": row["bucket_start"],
        "open": row["open"], "high": row["high"], "low": row["low"], "close": row["close"],
        "volume": row["volume"], "is_complete": bool(row["is_complete"]),
        "revision": row["revision"], "source": row["source"],
        "last_source_ms": row["last_source_ms"], "last_received_ms": row["last_received_ms"],
        "tick_count": row["tick_count"],
    }


class CandleStore:
    def __init__(self, conn: sqlite3.Connection, intervals: dict[str, int], grace_s: float = 3.0):
        self.conn = conn
        self.intervals = intervals
        self.grace_ms = int(grace_s * 1000)
        self._last_source_ms: dict[str, int] = {}
        self._last_cum_vol: dict[str, float] = {}
        # Restore ordering state after a restart so out-of-order detection survives it.
        for r in conn.execute(
            "SELECT symbol, MAX(source_time_ms) AS t FROM observations "
            "WHERE kind='tick' GROUP BY symbol"):
            self._last_source_ms[r["symbol"]] = r["t"]
            v = conn.execute(
                "SELECT day_volume FROM observations WHERE kind='tick' AND symbol=? "
                "AND source_time_ms=? ORDER BY id DESC LIMIT 1", (r["symbol"], r["t"])).fetchone()
            if v and v["day_volume"] is not None:
                self._last_cum_vol[r["symbol"]] = v["day_volume"]

    # ------------------------------------------------------------------ counters
    def _bump(self, name: str, n: int = 1):
        self.conn.execute(
            "INSERT INTO ingest_counters(name, value) VALUES(?, ?) "
            "ON CONFLICT(name) DO UPDATE SET value = value + excluded.value", (name, n))

    # ------------------------------------------------------------------ ticks
    def ingest_tick(self, tick: Tick, received_ms: int) -> dict:
        sym = tick.symbol
        key = f"{tick.source}|{sym}|{tick.source_time_ms}|{tick.price!r}|{tick.day_volume!r}"
        prev_max = self._last_source_ms.get(sym)
        arrival = "out_of_order" if prev_max is not None and tick.source_time_ms < prev_max else "in_order"

        delta = 0.0
        if arrival == "in_order" and tick.day_volume is not None:
            prev = self._last_cum_vol.get(sym)
            if prev is not None and tick.day_volume >= prev:
                delta = tick.day_volume - prev
            # first tick of the session, or the counter reset (new trading day): no volume attributed

        try:
            cur = self.conn.execute(
                "INSERT INTO observations(obs_key, kind, symbol, source, source_time_ms, received_time_ms,"
                " price, day_volume, volume_delta, market_hours, arrival, raw_json)"
                " VALUES (?, 'tick', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (key, sym, tick.source, tick.source_time_ms, received_ms, tick.price,
                 tick.day_volume, delta, tick.market_hours, arrival, json.dumps(tick.raw)))
        except sqlite3.IntegrityError:
            self._bump("duplicates")
            self.conn.commit()
            return {"status": "duplicate", "arrival": arrival, "observation_id": None, "candles": []}

        oid = cur.lastrowid
        if arrival == "in_order":
            self._last_source_ms[sym] = tick.source_time_ms
            if tick.day_volume is not None:
                self._last_cum_vol[sym] = tick.day_volume
        else:
            self._bump("out_of_order")

        changed = []
        for name, secs in self.intervals.items():
            changed += self._apply_tick(sym, name, secs, tick, delta, oid, received_ms, arrival)
        self.conn.commit()
        return {"status": "accepted", "arrival": arrival, "observation_id": oid, "candles": changed}

    def _get(self, sym, iv, bucket):
        return self.conn.execute(
            "SELECT * FROM candles WHERE symbol=? AND interval=? AND bucket_start=?",
            (sym, iv, bucket)).fetchone()

    def _write_revision(self, sym, iv, bucket, reason, oid, received_ms):
        row = self._get(sym, iv, bucket)
        self.conn.execute(
            "INSERT INTO candle_revisions(symbol, interval, bucket_start, revision, open, high, low, close,"
            " volume, is_complete, reason, observation_id, received_time_ms)"
            " VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (sym, iv, bucket, row["revision"], row["open"], row["high"], row["low"], row["close"],
             row["volume"], row["is_complete"], reason, oid, received_ms))
        d = _candle_dict(row)
        d["reason"] = reason
        return d

    def _finalize_before(self, sym, iv, bucket, received_ms) -> list[dict]:
        rows = self.conn.execute(
            "SELECT bucket_start FROM candles WHERE symbol=? AND interval=? AND bucket_start<? AND is_complete=0",
            (sym, iv, bucket)).fetchall()
        out = []
        for r in rows:
            self.conn.execute(
                "UPDATE candles SET is_complete=1, revision=revision+1 "
                "WHERE symbol=? AND interval=? AND bucket_start=?", (sym, iv, r["bucket_start"]))
            out.append(self._write_revision(sym, iv, r["bucket_start"], "finalize", None, received_ms))
        return out

    def _apply_tick(self, sym, iv, secs, tick: Tick, delta, oid, received_ms, arrival) -> list[dict]:
        t = tick.source_time_ms
        p = tick.price
        bucket = (t // 1000) // secs * secs
        row = self._get(sym, iv, bucket)
        out: list[dict] = []

        if row is None:
            out += self._finalize_before(sym, iv, bucket, received_ms)
            later = self.conn.execute(
                "SELECT 1 FROM candles WHERE symbol=? AND interval=? AND bucket_start>? LIMIT 1",
                (sym, iv, bucket)).fetchone()
            interval_over = (bucket + secs) * 1000 + self.grace_ms <= received_ms
            complete = 1 if (later or interval_over) else 0
            self.conn.execute(
                "INSERT INTO candles(symbol, interval, bucket_start, open, high, low, close, volume,"
                " is_complete, revision, source, first_source_ms, last_source_ms, last_received_ms, tick_count)"
                " VALUES (?,?,?,?,?,?,?,?,?,1,?,?,?,?,1)",
                (sym, iv, bucket, p, p, p, p, delta, complete, tick.source, t, t, received_ms))
            out.append(self._write_revision(sym, iv, bucket, "late" if complete else "open", oid, received_ms))
            return out

        o, h, l, c, v = row["open"], row["high"], row["low"], row["close"], row["volume"]
        first, last = row["first_source_ms"], row["last_source_ms"]
        no, nc = o, c
        if t >= last:
            nc, last = p, t
        if t < first:
            no, first = p, t
        nh, nl, nv = max(h, p), min(l, p), v + delta
        if (no, nh, nl, nc, nv) == (o, h, l, c, v):
            self.conn.execute(
                "UPDATE candles SET tick_count=tick_count+1, last_received_ms=?, first_source_ms=?, last_source_ms=? "
                "WHERE symbol=? AND interval=? AND bucket_start=?",
                (received_ms, first, last, sym, iv, bucket))
            return out
        reason = "late" if row["is_complete"] else ("out_of_order" if arrival == "out_of_order" else "tick")
        self.conn.execute(
            "UPDATE candles SET open=?, high=?, low=?, close=?, volume=?, revision=revision+1,"
            " first_source_ms=?, last_source_ms=?, last_received_ms=?, tick_count=tick_count+1 "
            "WHERE symbol=? AND interval=? AND bucket_start=?",
            (no, nh, nl, nc, nv, first, last, received_ms, sym, iv, bucket))
        out.append(self._write_revision(sym, iv, bucket, reason, oid, received_ms))
        return out

    # ------------------------------------------------------------------ clock-based completion
    def finalize_due(self, now_ms: int) -> list[dict]:
        out = []
        for iv, secs in self.intervals.items():
            rows = self.conn.execute(
                "SELECT symbol, bucket_start FROM candles WHERE interval=? AND is_complete=0 "
                "AND (bucket_start + ?) * 1000 + ? <= ?", (iv, secs, self.grace_ms, now_ms)).fetchall()
            for r in rows:
                self.conn.execute(
                    "UPDATE candles SET is_complete=1, revision=revision+1 "
                    "WHERE symbol=? AND interval=? AND bucket_start=?", (r["symbol"], iv, r["bucket_start"]))
                out.append(self._write_revision(r["symbol"], iv, r["bucket_start"], "finalize", None, now_ms))
        if out:
            self.conn.commit()
        return out

    # ------------------------------------------------------------------ historical bars
    def ingest_bar(self, bar: Bar, received_ms: int, now_ms: Optional[int] = None) -> dict:
        now_ms = now_ms if now_ms is not None else received_ms
        secs = self.intervals[bar.interval]
        key = (f"{bar.source}|{bar.symbol}|{bar.interval}|{bar.start}|"
               f"{bar.open!r}|{bar.high!r}|{bar.low!r}|{bar.close!r}|{bar.volume!r}")
        try:
            cur = self.conn.execute(
                "INSERT INTO observations(obs_key, kind, symbol, source, interval, source_time_ms,"
                " received_time_ms, price, open, high, low, volume, arrival)"
                " VALUES (?, 'bar', ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'history')",
                (key, bar.symbol, bar.source, bar.interval, bar.start * 1000, received_ms,
                 bar.close, bar.open, bar.high, bar.low, bar.volume))
        except sqlite3.IntegrityError:
            self._bump("duplicates")
            self.conn.commit()
            return {"status": "duplicate", "candles": []}
        oid = cur.lastrowid
        complete = 1 if (bar.start + secs) * 1000 <= now_ms else 0
        row = self._get(bar.symbol, bar.interval, bar.start)
        out = []
        if row is None:
            self.conn.execute(
                "INSERT INTO candles(symbol, interval, bucket_start, open, high, low, close, volume,"
                " is_complete, revision, source, first_source_ms, last_source_ms, last_received_ms, tick_count)"
                " VALUES (?,?,?,?,?,?,?,?,?,1,?,?,?,?,0)",
                (bar.symbol, bar.interval, bar.start, bar.open, bar.high, bar.low, bar.close, bar.volume,
                 complete, bar.source, bar.start * 1000, bar.start * 1000, received_ms))
            out.append(self._write_revision(bar.symbol, bar.interval, bar.start, "history", oid, received_ms))
        elif row["source"] == bar.source:
            # The source revised a bar it sent before (e.g. the still-forming last bar).
            self.conn.execute(
                "UPDATE candles SET open=?, high=?, low=?, close=?, volume=?, is_complete=?,"
                " revision=revision+1, last_received_ms=? WHERE symbol=? AND interval=? AND bucket_start=?",
                (bar.open, bar.high, bar.low, bar.close, bar.volume, complete, received_ms,
                 bar.symbol, bar.interval, bar.start))
            out.append(self._write_revision(bar.symbol, bar.interval, bar.start, "history", oid, received_ms))
        else:
            # A live-built candle already exists: the stream wins; the bar is kept only as an observation.
            self._bump("history_conflicts_kept_live")
        self.conn.commit()
        return {"status": "accepted", "candles": out}

    # ------------------------------------------------------------------ queries
    def get_candles(self, sym: str, iv: str, limit: int = 500) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM (SELECT * FROM candles WHERE symbol=? AND interval=? "
            "ORDER BY bucket_start DESC LIMIT ?) ORDER BY bucket_start", (sym, iv, limit)).fetchall()
        return [_candle_dict(r) for r in rows]

    def get_replay(self, sym: str, iv: str, limit: int = 2000) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM (SELECT * FROM candle_revisions WHERE symbol=? AND interval=? "
            "ORDER BY id DESC LIMIT ?) ORDER BY id", (sym, iv, limit)).fetchall()
        return [{"id": r["id"], "time": r["bucket_start"], "revision": r["revision"], "open": r["open"],
                 "high": r["high"], "low": r["low"], "close": r["close"], "volume": r["volume"],
                 "is_complete": bool(r["is_complete"]), "reason": r["reason"],
                 "received_time_ms": r["received_time_ms"]} for r in rows]

    def get_revisions(self, sym: str, iv: str, bucket: int) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM candle_revisions WHERE symbol=? AND interval=? AND bucket_start=? ORDER BY revision",
            (sym, iv, bucket)).fetchall()
        return [dict(r) for r in rows]

    def recent_observations(self, sym: Optional[str] = None, limit: int = 25) -> list[dict]:
        q = ("SELECT id, kind, symbol, source, interval, source_time_ms, received_time_ms, price,"
             " volume_delta, arrival FROM observations")
        args: tuple = ()
        if sym:
            q += " WHERE symbol=?"
            args = (sym,)
        q += " ORDER BY id DESC LIMIT ?"
        return [dict(r) for r in self.conn.execute(q, args + (limit,))]

    def stats(self) -> dict:
        c = self.conn
        counters = {r["name"]: r["value"] for r in c.execute("SELECT name, value FROM ingest_counters")}
        return {
            "ticks": c.execute("SELECT COUNT(*) FROM observations WHERE kind='tick'").fetchone()[0],
            "bars": c.execute("SELECT COUNT(*) FROM observations WHERE kind='bar'").fetchone()[0],
            "candles": c.execute("SELECT COUNT(*) FROM candles").fetchone()[0],
            "provisional": c.execute("SELECT COUNT(*) FROM candles WHERE is_complete=0").fetchone()[0],
            "revisions": c.execute("SELECT COUNT(*) FROM candle_revisions").fetchone()[0],
            "duplicates": counters.get("duplicates", 0),
            "out_of_order": counters.get("out_of_order", 0),
            "late_revisions": c.execute(
                "SELECT COUNT(*) FROM candle_revisions WHERE reason='late'").fetchone()[0],
            "history_conflicts_kept_live": counters.get("history_conflicts_kept_live", 0),
        }

    # ------------------------------------------------------------------ feed events
    def record_feed_event(self, time_ms: int, state: str, detail: str = ""):
        self.conn.execute("INSERT INTO feed_events(time_ms, state, detail) VALUES (?,?,?)",
                          (time_ms, state, detail))
        self.conn.commit()

    def recent_feed_events(self, limit: int = 30) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM feed_events ORDER BY id DESC LIMIT ?", (limit,))]
