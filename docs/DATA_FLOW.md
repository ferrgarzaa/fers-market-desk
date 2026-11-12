# Data flow

```
 Yahoo Finance streamer             yfinance HTTP history (startup backfill)
 wss://streamer.finance.yahoo.com    Ticker.history(period, interval)
        │ base64 protobuf frames                │ OHLCV bars
        ▼                                       ▼
 ┌──────────────── backend (FastAPI, app/) ─────────────────────────────┐
 │ feed.YahooFeed                                                        │
 │  • connect → subscribe [symbols] → resend subscribe every 15 s        │
 │  • decode with yfinance.pricing_pb2.PricingData                       │
 │  • states: connecting → connected → live → stale / unavailable        │
 │  • on error: record reason, retry with backoff 2 s → 30 s             │
 │        │ Tick(symbol, price, source_time_ms, day_volume)              │
 │        ▼                                                              │
 │ store.CandleStore.ingest_tick(tick, received_ms)                      │
 │  1. identity key → INSERT observations (UNIQUE obs_key)               │
 │       duplicate? → counter++, stop                                    │
 │  2. classify arrival: in_order / out_of_order                         │
 │  3. volume delta from cumulative counter (in-order ticks only)        │
 │  4. for 1m, 5m, 15m: update the bucket's candle; every change         │
 │       → revision++ and an INSERT into candle_revisions                │
 │  5. a new bucket finalizes the earlier provisional candles            │
 │ main.Hub.clock_loop (every 1 s)                                       │
 │  • finalize_due(): interval end + grace passed → complete             │
 │  • stale detection (no message for 30 s)                              │
 │  • broadcast status (feed snapshot + DB counters)                     │
 │        │ JSON over WebSocket /ws                                      │
 └────────┼──────────────────────────────────────────────────────────────┘
          ▼
 Vue (frontend/src) store.js → ChartPanel (lightweight-charts v5), Watchlist,
 TickerTape, FeedPanel, IntegrityPanel, ObservationsPanel, EventLog, ReplayPanel
```

## Messages over `/ws`

Server → browser

| type | payload | sent when |
|---|---|---|
| `snapshot` | `symbol, interval, candles[]` (current versions, ≤500) | on connect, subscribe, end of replay, after backfill |
| `candle` | one candle with `revision`, `is_complete`, `reason` | each revision of the subscribed pair |
| `tick` | `symbol, price, source_time_ms, received_ms, change_percent, arrival` | every accepted or duplicate tick (feeds the tape and watchlist) |
| `status` | feed snapshot, DB counters, `server_now_ms`, last tick for each symbol | every second, and on every state change |
| `feed_event` / `events` | feed state changes | when the state changes / on connect |
| `observations` | the newest stored observations for the symbol | every 2 s (requested by the client) |
| `replay_start` / `replay_candle` / `replay_done` | stored revisions, in order | during replay |

Browser → server: `subscribe {symbol, interval}`, `replay {speed}`, `stop_replay`, `observations`.

REST endpoints (useful for tests and inspection): `GET /api/health`, `/api/status`, `/api/candles`, `/api/replay`, `/api/revisions`, `/api/observations`, `/api/feed-events`, and `POST /api/feed/outage {enabled}`.

## Time fields
* **source time**: the timestamp Yahoo put on the quote (`PricingData.time`). Seconds are normalized to milliseconds.
* **receipt time**: the moment our backend received the frame.
* **data age** in the UI = browser now − source time. It measures how old the market information is. A display that refreshes often does not make old data current, which is why the age is shown on its own.
* Candle buckets are aligned on the **source time**: `floor(source_s / interval) * interval`, in UTC epoch seconds. Charts display them in ET.

## Duplicate, revised and out-of-order observations

| Case | Detection | Effect |
|---|---|---|
| **Exact duplicate** (same source, symbol, source time, price and cumulative volume) | `UNIQUE(obs_key)` violation | Not stored again and no candle change. `ingest_counters.duplicates` is incremented |
| Same source time with a **different price** | a different key | Treated as a new observation and can revise the close |
| **Revision** (any change to a candle) | the O/H/L/C/V or completeness differs | `candles.revision` += 1, and a full copy goes to `candle_revisions` with the reason (`open`, `tick`, `out_of_order`, `late`, `finalize`, `history`) and the observation id. A tick that changes nothing creates no revision |
| **Out-of-order tick** (source time < newest seen for that symbol) | compared with `_last_source_ms` (restored from SQLite after a restart) | Stored with `arrival='out_of_order'`. It can widen the high or low, and it becomes the **open** if it is earlier than the candle's first tick. It never replaces the **close**, which belongs to the latest source time. It adds no volume |
| **Late tick** for a candle already complete | `is_complete = 1` | The candle is revised (`reason='late'`) and **stays complete** |
| **History bar vs. live candle** for the same bucket | `candles.source` differs | The live-built candle is kept. The bar is still stored as an observation, and `history_conflicts_kept_live` is incremented |
| History bar re-sent with new values (forming bar) | same source | Revised (`reason='history'`) |

## Completed vs. provisional candles
A candle is **provisional** (`is_complete=0`) while its interval may still receive data. It becomes **complete** when:
1. a tick for a later bucket of the same symbol and interval arrives, or
2. the wall clock passes `bucket_end + FINALIZE_GRACE_S` (`finalize_due`, checked every second).

The UI marks the provisional candle with a faded body, a dashed PROVISIONAL price line and a `◌ PROVISIONAL` tag. Part 4.2 indicators will read only complete candles for confirmed signals.

## Replay
`candle_revisions` is append-only, so replaying it in `id` order reproduces exactly what the chart showed while the data arrived: each candle forms, gets revised and then finalizes. Replay is per client and labelled **REPLAY — not live**. "Back to live" re-subscribes and receives a fresh snapshot.
