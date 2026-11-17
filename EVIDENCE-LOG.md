# Evidence log (curated, redacted)

Each entry links an intention, the instruction that produced it, the resulting change, an observation, the decision taken and any remaining uncertainty. No credentials or personal data appear here (none are needed by the project).

---

### 1. Revised approach — owning the Yahoo WebSocket loop
* **Intended change:** make the feed state (connected, live, unavailable) visible, as the assignment requires.
* **Instruction (excerpt):** "Make the data source, age, and feed status visible … including an unavailable-feed condition."
* **Observation:** reading `yfinance/live.py` (v1.8.0) showed that `AsyncWebSocket.listen()` catches exceptions, sleeps 3 s and reconnects internally, and that `YfConfig.debug.hide_exceptions` defaults to `True`. The application would never learn that the feed was down.
* **Decision / change:** `backend/app/feed.py::YahooFeed.run` connects with `websockets`, sends the same subscribe and 15-second heartbeat, and decodes with yfinance's `PricingData` protobuf:
  ```python
  except Exception as e:
      self.reconnect_attempts += 1
      await self.set_state("unavailable",
          f"{type(e).__name__}: {e} – retry #{self.reconnect_attempts} in {backoff:.0f}s")
      await asyncio.sleep(backoff)
      backoff = min(backoff * 2, self.backoff_max)
  ```
* **Test:** `test_unreachable_source_reports_unavailable_and_retries`. Screenshot of a real failure: `docs/evidence/real-unavailable-feed.png`. The sandbox proxy rejected Yahoo with HTTP 403; the UI showed `UNAVAILABLE`, the error text and `retry #5 in 8s`.
* **Uncertainty:** Yahoo's streamer is unofficial and may change its format without notice.

### 2. Failure — request body parsed as a query parameter (HTTP 422)
* **Intended change:** a `POST /api/feed/outage {"enabled": true}` endpoint for demonstrating the outage.
* **Observation:** `test_ws_snapshot_live_candles_and_outage` failed with `KeyError: 'state'`, because the response was a 422 validation error rather than the feed snapshot.
* **Cause:** the Pydantic model `OutageBody` was defined *inside* `create_app()`. With `from __future__ import annotations`, FastAPI could not resolve the string annotation, so it treated `body` as a query parameter.
* **Decision / change:** moved `OutageBody` to module level in `backend/app/main.py`. The test passed (22/22).
* **Lesson:** postponed annotations and locally defined models do not mix in FastAPI.

### 3. Revised approach — backfill blocked the live stream
* **Observation:** the first version awaited 15 history calls (5 symbols × 3 intervals) *before* starting the feed. When Yahoo was slow or unreachable, the dashboard waited 20 s or more before streaming.
* **Decision:** the feed starts first and the backfill runs as a parallel task (`Hub.backfill_then_refresh`), which re-sends snapshots when it finishes. Conflicts are resolved by a rule: a live-built candle wins (`history_conflicts_kept_live`, tested by `test_history_never_overwrites_live_built_candle`).

### 4. Design decision — the close belongs to the newest source time
* **Question:** what should happen to a candle when a tick arrives with an older source time?
* **Decision:** an out-of-order tick may widen the high or low, and becomes the open if it is earlier than the first tick, but it never replaces the close and adds no volume.
* **Test:** `test_out_of_order_tick_widens_range_but_never_replaces_close`. The low becomes 90, the close stays 102, the volume stays 10, and the revision reason is `out_of_order`.

### 5. Verification — browser test of the whole UI path
* **Command:** `npx playwright test` (backend in fake mode plus Vite).
* **Observation:** the test passed in 2.0 s and produced the screenshots `docs/evidence/e2e-live.png`, `e2e-outage.png` and `e2e-replay.png`.
* **Uncertainty:** the browser test uses the fake feed. The live Yahoo path is shown in the demo video.

### 6. Live observation — real disconnect and automatic recovery (student's laptop)
* **Question:** does the live path behave as designed outside the test sandbox?
* **Observation (SQLite `feed_events` on my machine, Nov 12 2026, ET):** LIVE from 14:38:13; simulated outage 14:40:37 → LIVE 14:40:38; **real Yahoo disconnect** 14:58:29 `ConnectionClosedError: no close frame received or sent – retry #1 in 2s` → connecting → connected → LIVE at 14:58:36. 4,236 `yahoo_ws` ticks stored by 15:16.
* **Decision:** no change needed. This confirms design decision #1 (owning the socket loop): the failure was visible, logged with its cause, and recovered without user action.
* **Uncertainty:** two history requests for BTC-USD timed out (20 s), so those intervals started without backfilled bars; the stream itself was unaffected.

---
## Part 4.2

### 7. Failure — a hand-computed expected value was wrong, the code was right
* **Intended change:** check the simulated accounting against a known example that includes fees and slippage.
* **Instruction (excerpt):** "Check simulated accounting against known examples."
* **Observation:** `test_round_trip_with_fee_and_slippage_hand_example` failed: `assert 967.0494423118125 == 967.0727 ± 0.001`.
* **Evidence used:** the same test also asserts the result against the formula written out independently (`proceeds = 109.945 × qty × 0.999`, `qty = 10,000 / (100.05 × 1.001)`), and that assertion **passed**. Recomputing by hand: qty = 99.85017, px × qty = 10,978.03, × 0.999 = 10,967.05, − 10,000 basis = **967.05**. The estimate 967.07 had been rounded too early.
* **Decision:** keep the code and correct the constant to 967.0494. Expected numbers in tests are now computed step by step and written down (docs/STRATEGY.md §2), never estimated.
* **Relevant generated code** (`backend/app/broker.py`):
  ```python
  px = bar_open * (1 - c.slippage)
  qty = pos["qty"]
  fee = px * qty * c.fee_rate
  realized = px * qty - fee - pos["avg_cost"] * qty
  ```

### 8. Revised approach — browser tests failed in a cascade
* **Observation:** after the observations table moved into a tabbed panel, the 4.1 browser test failed at `getByTestId('event')`, because the *Observations* tab was still open and the event log was hidden. The new 4.2 test then failed with `FEED UNAVAILABLE`. The first test had stopped halfway with the simulated outage still on, and both tests share one backend.
* **Decision:** add `tab-events` and `tab-obs` test ids and switch tabs explicitly. Also, a screenshot showed a backtest period of "Nov 12 → Nov 17" in a fake-feed run, which proved the test database was being **reused across runs**. `playwright.config.js` now creates a fresh database for each run (`os.tmpdir()/fers-e2e-<timestamp>.db`).
* **Result:** 2/2 browser tests pass, and the results no longer depend on earlier runs.

### 9. Design decision — signal at the close, fill at the next open
* **Question:** at what price should a crossover trade?
* **Decision:** the close that produces the signal is already in the past when the signal is known, so filling at that close is a hidden look-ahead. Orders are filled at the **open of the next candle** ± slippage.
* **Tests:** `test_hand_example_trades_at_next_open` (BUY signal at the bar-6 close of 12 → filled at the bar-7 open of 12; SELL → bar-10 open of 9; −$2,500), plus the truncation and future-perturbation look-ahead tests.

### 10. Verification — the live bot and the backtest make identical trades
* **Question:** could the live (incremental, event-driven) path and the backtest disagree?
* **Test:** `test_live_bot_makes_exactly_the_backtest_trades` feeds 500 candles to `LiveTrader`, each as an "open" event and then a "complete" event, and compares the fills with `run_backtest` on the same candles. They match on bar, side, price and quantity (to 1e-8).
* **Live observation (fake feed, local run):** TSLA crossed up on the 17:16 UTC 1m candle. The order stayed *pending* and was filled at the **17:17 open**: 330.5389 × 1.0005 = 330.7042, fee $9.99, cash exactly $90,000.00. The account then showed equity − 100,000 = realized + unrealized = −0.6638. The same run recorded an AAPL SELL as *skipped — no position to sell*.
* **Uncertainty:** that run used the fake feed. The Yahoo run is shown in the video and in the report.
