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

---
## Part 4.2 tables (`backend/app/broker.py`)

### `sim_accounts`
`account_id` (PK: `live` for the bot; a backtest uses its own in-memory account), `kind`, `starting_cash`, `cash`, `fee_rate`, `slippage`, `alloc`, `created_ms`, `params_json`. An existing account keeps the settings it was created with.

### `sim_orders` — every signal becomes an order row, even when it is not executed
`id, account_id, symbol, side (BUY|SELL), status (pending|filled|skipped), reason, signal_bar` (bucket of the completed candle whose close produced the signal), `signal_close, sma_fast, sma_slow, created_ms, filled_ms, note` (why it was skipped).

### `sim_fills` — executions
`id, account_id, order_id → sim_orders, symbol, side, qty, ref_price` (open of the fill candle), `fill_price` (after slippage), `fee, fill_bar` (bucket of the fill candle), `realized_pnl` (SELL only), `cash_after, time_ms`.

### `sim_positions`
`(account_id, symbol)` PK, `qty, avg_cost` (includes the buy fee), `opened_bar`. Long-only, so there is at most one row per symbol.

### `backtest_runs`
`id, created_ms, symbol, interval, fast, slow, bars, first_bar, last_bar, params_json` (costs and sizing), `metrics_json, trades_json, equity_json` (the curve and its benchmark).

```sql
-- the bot's decisions and what happened to each one
SELECT o.id, o.symbol, o.side, o.status, o.note, datetime(o.signal_bar,'unixepoch') AS signal_bar,
       f.fill_price, f.qty, f.fee, f.realized_pnl
FROM sim_orders o LEFT JOIN sim_fills f ON f.order_id = o.id
WHERE o.account_id = 'live' ORDER BY o.id;
```
