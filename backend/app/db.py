"""SQLite schema and connection helper.

Tables
------
observations      every accepted raw observation (a streamed tick or a historical bar)
candles           the CURRENT version of each (symbol, interval, bucket) candle
candle_revisions  every version a candle has ever had (append-only history)
feed_events       feed state changes (connecting, live, stale, unavailable ...)
ingest_counters   running counters (duplicates rejected, out-of-order ticks ...)

See docs/SCHEMA.md for the full explanation.
"""
import sqlite3
from pathlib import Path

SCHEMA = """
CREATE TABLE IF NOT EXISTS observations (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    obs_key           TEXT    NOT NULL UNIQUE,      -- identity used for de-duplication
    kind              TEXT    NOT NULL,             -- 'tick' | 'bar'
    symbol            TEXT    NOT NULL,
    source            TEXT    NOT NULL,             -- 'yahoo_ws' | 'yahoo_history' | 'fake'
    interval          TEXT,                         -- bars only
    source_time_ms    INTEGER NOT NULL,             -- time stamped by the source
    received_time_ms  INTEGER NOT NULL,             -- time our backend received it
    price             REAL    NOT NULL,             -- tick price / bar close
    open REAL, high REAL, low REAL, volume REAL,    -- bars only
    day_volume        REAL,                         -- cumulative volume reported by source
    volume_delta      REAL    NOT NULL DEFAULT 0,   -- volume attributed to this tick
    market_hours      INTEGER,                      -- Yahoo market-hours code
    arrival           TEXT    NOT NULL,             -- 'in_order' | 'out_of_order' | 'history'
    raw_json          TEXT
);
CREATE INDEX IF NOT EXISTS ix_obs_symbol_time ON observations(symbol, source_time_ms);

CREATE TABLE IF NOT EXISTS candles (
    symbol            TEXT    NOT NULL,
    interval          TEXT    NOT NULL,
    bucket_start      INTEGER NOT NULL,             -- epoch seconds, UTC
    open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
    volume            REAL    NOT NULL DEFAULT 0,
    is_complete       INTEGER NOT NULL DEFAULT 0,   -- 0 = provisional, 1 = interval closed
    revision          INTEGER NOT NULL DEFAULT 1,
    source            TEXT    NOT NULL,
    first_source_ms   INTEGER NOT NULL,
    last_source_ms    INTEGER NOT NULL,
    last_received_ms  INTEGER NOT NULL,
    tick_count        INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (symbol, interval, bucket_start)
);

CREATE TABLE IF NOT EXISTS candle_revisions (
    id                INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol            TEXT    NOT NULL,
    interval          TEXT    NOT NULL,
    bucket_start      INTEGER NOT NULL,
    revision          INTEGER NOT NULL,
    open REAL NOT NULL, high REAL NOT NULL, low REAL NOT NULL, close REAL NOT NULL,
    volume            REAL    NOT NULL,
    is_complete       INTEGER NOT NULL,
    reason            TEXT    NOT NULL,             -- open | tick | out_of_order | late | finalize | history
    observation_id    INTEGER REFERENCES observations(id),
    received_time_ms  INTEGER NOT NULL,
    UNIQUE (symbol, interval, bucket_start, revision)
);
CREATE INDEX IF NOT EXISTS ix_rev_pair ON candle_revisions(symbol, interval, id);

CREATE TABLE IF NOT EXISTS feed_events (
    id        INTEGER PRIMARY KEY AUTOINCREMENT,
    time_ms   INTEGER NOT NULL,
    state     TEXT    NOT NULL,
    detail    TEXT
);

CREATE TABLE IF NOT EXISTS ingest_counters (
    name  TEXT PRIMARY KEY,
    value INTEGER NOT NULL DEFAULT 0
);
"""


def connect(path) -> sqlite3.Connection:
    """Open (and create if needed) the database and apply the schema.
    `path` may be ':memory:' for tests."""
    if str(path) != ":memory:":
        Path(path).parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path), check_same_thread=False)
    conn.row_factory = sqlite3.Row
    if str(path) != ":memory:":
        conn.execute("PRAGMA journal_mode=WAL")
    conn.executescript(SCHEMA)
    conn.commit()
    return conn
