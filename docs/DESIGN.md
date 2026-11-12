# Design notes

## Stack
Vue 3 (Vite), FastAPI, SQLite, all on localhost, as the course requires. Charting uses **TradingView Lightweight Charts v5**. It is purpose-built for financial data: candlesticks, a histogram series in its own **pane** for volume, per-bar colours (used for provisional candles), dashed price lines, and `update(bar, historicalUpdate)` for revising older candles. It is small (~250 KB bundle total) and open source. The TradingView attribution logo is left on, as the licence requires.

## Key decisions
1. **Own WebSocket loop, yfinance protobuf schema.** yfinance's `AsyncWebSocket.listen()` reconnects internally and swallows errors, so the app could not see whether it was connected, how many retries had happened, or why. `feed.YahooFeed` opens the same Yahoo URL with the `websockets` library, sends the same subscribe and heartbeat messages, and decodes with `yfinance.pricing_pb2.PricingData`. That makes every state observable and logged.
2. **Persist before broadcast.** A tick is written to SQLite *before* it reaches the browser, so anything on the chart can be found in the database and replayed.
3. **Append-only revisions instead of overwriting.** `candles` holds the current version for fast snapshots, while `candle_revisions` keeps every version. That gives an audit trail, replay, and the evidence for "revised" observations from a single mechanism.
4. **Close belongs to the newest source time.** This rule makes out-of-order handling deterministic: late or old ticks can widen the high and low or set an earlier open, but they can never move the close backwards.
5. **Volume from cumulative counters.** Yahoo sends a cumulative `day_volume` (or `vol_24hr` for crypto), not the size of each trade. The per-candle volume is the sum of positive in-order deltas, and resets or out-of-order counters contribute 0. It is approximate, and the UI and report say so.
6. **Two completion triggers.** A newer bucket finalizes a candle immediately. The clock with a grace period finalizes it when the source is quiet, for example an illiquid stock.
7. **Separate "stale" from "unavailable".** Connected but silent (market closed, quiet symbol) is a different situation from not connected (network or server error). Both show in the badge, the banner, the panel and the event log. **Data age** comes from the *source* timestamp, so a frequently refreshed screen cannot hide old data.
8. **Crypto + stocks.** BTC-USD and ETH-USD stream 24/7, so the live path can be demonstrated at any hour. The stocks show the NYSE session state.
9. **History in parallel, live wins.** Startup backfill (`yfinance` HTTP) runs while the stream is already live. When both exist for the same bucket, the live-built candle is kept.
10. **Fake feed only for tests.** `FEED_MODE=fake` exists so CI and browser tests are deterministic and need no network. The UI labels it "FAKE synthetic feed (tests only)" everywhere. The graded demo uses `yahoo`.

## UI (chosen by the student)
* Theme: dark purple and pink. Background `#13101c`, panels `#1c1729`, up `#4ade80`, down `#f472b6`, accent `#a855f7`, text `#e9e4f5`.
* Font: JetBrains Mono, with tabular numbers so digits line up, in a Bloomberg-terminal style.
* Layout: a dense terminal grid with the watchlist and replay on the left, the chart and stored observations in the centre, and feed status, SQLite integrity and the event log on the right.
* Extras: scrolling ticker tape, a green or pink flash when a price changes, a provisional candle with a faded body and a dashed line, an ET clock and the NYSE session.
* Interval selector: 1m, 5m and 15m, all maintained at the same time by the backend.
