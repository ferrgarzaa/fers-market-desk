# Assignment 4.1 — Market Data and the Dashboard

**Student:** YOUR_NAME ([ferrgarzaa](https://github.com/ferrgarzaa)) · IST 402
**Application:** *Fer's Market Desk* — a local live market workstation

| | |
|---|---|
| **GitHub repository** | https://github.com/ferrgarzaa/fers-market-desk |
| **Submitted commit** | `09d723735e581678aa6bc50fbc06248036ff9fd1` — https://github.com/ferrgarzaa/fers-market-desk/commit/09d723735e581678aa6bc50fbc06248036ff9fd1 |
| **Demo video (30–60 s)** | VIDEO_LINK |
| **CI** | https://github.com/ferrgarzaa/fers-market-desk/actions |

---

## 1. What was completed

**Live visualization**
* A Yahoo Finance live stream (`wss://streamer.finance.yahoo.com`, decoded with yfinance's `PricingData` protobuf) for **BTC-USD, ETH-USD, AAPL, TSLA and NVDA**. The two crypto pairs stream 24/7, so the live path can be shown at any hour.
* FastAPI builds **1m / 5m / 15m candles** from the ticks. The browser receives them over a **WebSocket (`/ws`)** and draws them with **TradingView Lightweight Charts v5**: candlesticks plus a separate **volume pane**, with an interval selector.
* **Source, data age and feed status are always visible.** The top-bar badge, the chart's "SOURCE / DATA AGE" strip, the Feed status panel (source time, receipt time, transit, last message, reconnects) and the per-symbol age in the watchlist all show them. Age is measured from the **source timestamp**, so a frequently refreshing screen cannot hide old data. Feed states are LIVE, CONNECTED, CONNECTING, **STALE** (connected but silent, e.g. market closed) and **UNAVAILABLE** (with the real error and the retry count).
* Unfinished candles are visibly **PROVISIONAL**: faded body, dashed purple price line and a `◌ PROVISIONAL` tag, compared with `✓ COMPLETE`.
* UI choices (all mine): a dark purple/pink theme, a Bloomberg-style terminal grid, JetBrains Mono, a scrolling ticker tape, a green or pink price flash, and an ET clock with the NYSE session.

**Persistence and replay (SQLite)**
* `observations` stores every accepted tick and history bar with its **identity key** (`UNIQUE obs_key`), **source time**, **receipt time**, source, arrival class and raw frame.
* `candles` holds the current version of each candle with `revision` and **`is_complete`**. `candle_revisions` keeps **every version** with the reason (`open/tick/out_of_order/late/finalize/history`) and the observation that caused it.
* `feed_events` logs every connect, failure, retry and stale period. `ingest_counters` counts duplicates and out-of-order arrivals.
* **Replay** streams the stored revisions back, in the order they were recorded, labelled *REPLAY — not live*. It works with the market closed.

**Working evidence**
* The full path Yahoo → `YahooFeed` → `CandleStore` (SQLite) → `Hub` → `/ws` → chart is shown in the demo video.
* **Unavailable feed:** a *Simulate feed outage* button closes the real Yahoo socket. A **real** failure was also captured: the development sandbox blocks Yahoo, and the app showed `UNAVAILABLE · InvalidProxyStatus: HTTP 403 – retry #5 in 8s` ([screenshot](docs/evidence/real-unavailable-feed.png)).
* Documents: [README](README.md) (startup, database initialization, configuration; no credentials are needed or stored), [AGENTS.md](AGENTS.md), [docs/DATA_FLOW.md](docs/DATA_FLOW.md), [docs/SCHEMA.md](docs/SCHEMA.md), [docs/DESIGN.md](docs/DESIGN.md), [docs/VERIFICATION.md](docs/VERIFICATION.md), [AI-USE.md](AI-USE.md), [EVIDENCE-LOG.md](EVIDENCE-LOG.md).

## 2. Key design decisions
1. **Own WebSocket loop with yfinance's protobuf schema.** `yfinance.AsyncWebSocket.listen()` hides exceptions and reconnects silently, so the app could not report *why* the feed was down. Managing the socket made every state observable ([evidence log #1](EVIDENCE-LOG.md)).
2. **Persist before broadcast.** Everything on the chart is already in SQLite and can be replayed.
3. **Append-only revisions** instead of overwriting rows. One mechanism gives the audit trail, the evidence for revisions, and replay.
4. **Rules for messy data** ([DATA_FLOW](docs/DATA_FLOW.md#duplicate-revised-and-out-of-order-observations)):
   * *duplicate* → rejected by the UNIQUE identity, counted, and changes nothing;
   * *revision* → `revision+1` and a new `candle_revisions` row, and only when a value actually changes;
   * *out-of-order* → may widen the high or low, or set an earlier open, but **never replaces the close** (the close belongs to the newest source time) and adds no volume;
   * *late tick for a complete candle* → revises it and the candle stays complete;
   * *history bar vs. a live-built candle* → the live candle wins.
5. **Two completion triggers:** a tick in a newer bucket, or the clock passing the interval end plus a 3-second grace period.
6. **STALE is separate from UNAVAILABLE:** "connected but quiet" and "cannot connect" call for different reactions from the user.
7. **History backfill runs in parallel** with the live stream, so a slow history API never delays live data ([evidence log #3](EVIDENCE-LOG.md)).

## 3. Verification results
* **Backend: 22/22 pytest tests pass.** They cover duplicates, same-time/different-price, the revision sequence, no phantom revisions, the out-of-order close/open/volume rules, completion by new bucket and by clock, late revisions, cumulative-volume reset, history/live merging, replay order, restart persistence, decoding Yahoo's real protobuf format, a **real unreachable source → UNAVAILABLE plus backoff**, outage and recovery, and an end-to-end WebSocket/API test.
* **Browser: the Playwright test passes.** Feed badge LIVE, chart canvas, prices, data age, provisional tag, stored observations, interval switch, **outage banner, state and event**, recovery, replay. Screenshots: [live](docs/evidence/e2e-live.png), [outage](docs/evidence/e2e-outage.png), [replay](docs/evidence/e2e-replay.png).
* **GitHub Actions** runs both suites on every push.
* **Mocked vs. live:** the automated tests use the clearly labelled fake feed or synthetic frames. The live Yahoo path is shown in the video, and the unavailable state was also observed on a real network failure. The full table is in [VERIFICATION.md](docs/VERIFICATION.md).

## 4. Remaining limitations
* Yahoo's streamer is **unofficial and undocumented**. It sends a message only when a quote changes, so a quiet symbol can look stale while the market is open.
* **Per-candle volume is approximate.** It is derived from cumulative `day_volume` / `vol_24hr` differences. Crypto's rolling 24-hour volume can fall, and those deltas are counted as 0.
* The first live candle after startup may begin mid-interval. When a history bar exists for that bucket, the live candle is kept, so its open can differ from Yahoo's bar.
* The NYSE session indicator does **not model exchange holidays** or half days.
* Candle completion by the clock uses the backend's wall clock, so a badly skewed system clock would finalize candles early or late.
* Replay is limited to the most recent 1,500 revisions of the selected pair.
* Browser tests run against the fake feed. The live stream is verified manually and in the video.
* The SMA indicators, simulated trading and backtesting are scheduled for Part 4.2.
