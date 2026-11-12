# SQLite schema (`backend/app/db.py`)

The database is created automatically at startup (`CREATE TABLE IF NOT EXISTS`) and runs in WAL mode. Default file: `backend/data/market.db`, which git ignores. To reset it, delete the folder.

## `observations` — every accepted raw observation
| column | type | notes |
|---|---|---|
| `id` | INTEGER PK | insertion order = receipt order |
| `obs_key` | TEXT **UNIQUE** | identity: `source\|symbol\|source_time_ms\|price\|day_volume` for ticks; source, symbol, interval, start and OHLCV for bars |
| `kind` | TEXT | `tick` (stream) or `bar` (history) |
| `symbol`, `source` | TEXT | source is `yahoo_ws`, `yahoo_history`, `fake` or `fake_history` |
| `interval` | TEXT | bars only |
| `source_time_ms` | INTEGER | timestamp from the source |
| `received_time_ms` | INTEGER | time our backend received it |
| `price` | REAL | tick price, or the bar close |
| `open, high, low, volume` | REAL | bars only |
| `day_volume` | REAL | cumulative volume reported by Yahoo |
| `volume_delta` | REAL | volume attributed to this tick |
| `market_hours` | INTEGER | Yahoo market-hours code |
| `arrival` | TEXT | `in_order`, `out_of_order` or `history` |
| `raw_json` | TEXT | the decoded frame, kept for audit |

Index: `(symbol, source_time_ms)`.

## `candles` — current version of each candle
Primary key `(symbol, interval, bucket_start)`. Columns: `open, high, low, close, volume`, `is_complete` (0 = provisional), `revision`, `source`, `first_source_ms`, `last_source_ms` (used for the out-of-order open and close rules), `last_received_ms`, `tick_count`.

## `candle_revisions` — append-only history of every candle version
`id` (global order, used by replay), `symbol, interval, bucket_start, revision`, the full `OHLCV`, `is_complete`, `reason` (`open|tick|out_of_order|late|finalize|history`), `observation_id` (the observation that caused the revision; NULL for clock finalization), and `received_time_ms`.
`UNIQUE(symbol, interval, bucket_start, revision)`; index `(symbol, interval, id)`.

## `feed_events`
`id, time_ms, state, detail`. Stores startup, connecting, connected, live, stale, unavailable (with the error and the retry count) and `history_unavailable`.

## `ingest_counters`
`name, value`. Holds `duplicates`, `out_of_order` and `history_conflicts_kept_live`. Duplicates are counted but not stored, because storing them would make them stop being duplicates.

## Useful queries
```sql
-- how one candle evolved
SELECT revision, open, high, low, close, volume, is_complete, reason
FROM candle_revisions WHERE symbol='BTC-USD' AND interval='1m' AND bucket_start=1762957200
ORDER BY revision;

-- out-of-order arrivals
SELECT id, symbol, source_time_ms, received_time_ms, price FROM observations WHERE arrival='out_of_order';

-- outage history
SELECT datetime(time_ms/1000,'unixepoch'), state, detail FROM feed_events ORDER BY id DESC LIMIT 20;
```
