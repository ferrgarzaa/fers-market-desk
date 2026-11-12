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
