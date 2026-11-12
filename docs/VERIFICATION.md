# Verification

## Automated (run on every push by GitHub Actions)

### Backend — `cd backend && python -m pytest -v` (22 tests, all passing)
| Test | Claim it checks |
|---|---|
| `test_first_tick_opens_provisional_candle` | The first tick creates a provisional candle aligned to its bucket |
| `test_exact_duplicate_is_rejected_and_changes_nothing` | Duplicate identity → rejected, counted, candle unchanged |
| `test_same_time_different_price_is_not_a_duplicate` | The identity includes the price |
| `test_revisions_are_recorded_for_every_change` | Revision numbers 1, 2, 3 are stored with their closes and reasons |
| `test_unchanged_tick_does_not_create_revision` | No phantom revisions |
| `test_out_of_order_tick_widens_range_but_never_replaces_close` | Out-of-order rule; stale counter adds no volume |
| `test_out_of_order_tick_earlier_than_first_becomes_open` | Earlier late tick → true open |
| `test_new_bucket_finalizes_previous_candle` | Completion trigger (a); intervals are independent |
| `test_clock_finalizes_after_interval_plus_grace` | Completion trigger (b) and the grace boundary |
| `test_late_tick_revises_completed_candle_and_keeps_it_complete` | Late revision of a complete candle |
| `test_volume_from_cumulative_counter_and_reset` | Volume deltas and counter reset |
| `test_history_bar_then_live_ticks_revise_it` | History plus live merge; re-backfill is a duplicate |
| `test_history_never_overwrites_live_built_candle` | The live candle wins |
| `test_replay_returns_revisions_in_recorded_order` | Replay order |
| `test_out_of_order_detection_survives_restart` | State is restored from SQLite |
| `test_decode_real_format_frame` | Decodes a frame built with Yahoo's actual protobuf schema |
| `test_seconds_timestamp_is_normalized_to_ms`, `test_incomplete_message_is_ignored` | Defensive parsing |
| `test_unreachable_source_reports_unavailable_and_retries` | **Real** connection failure → UNAVAILABLE and retries with backoff |
| `test_simulated_outage_stops_data_and_recovers` | The outage toggle stops data and recovers |
| `test_ws_snapshot_live_candles_and_outage` | End to end through FastAPI: WS snapshot → subscribe → live candles; outage stops storage; events logged; replay endpoint |
| `test_rejects_unknown_symbol` | Input validation |

### Browser — `cd frontend && npx playwright test`
`e2e/dashboard.spec.js` starts the real backend (`FEED_MODE=fake`) and Vite, then checks:
the feed badge shows LIVE, the chart canvas renders, the watchlist has prices, data age is shown, the provisional candle tag is visible, stored observations are listed, the interval selector works, **the outage banner, panel state and event log entry appear**, the feed recovers to LIVE, and the replay banner appears and returns to live. The screenshots are saved to `docs/evidence/e2e-*.png`.

## Mocked vs. live — what each piece of evidence establishes
| Evidence | Mocked or live | What it establishes |
|---|---|---|
| Unit and API tests | Mocked ticks and the fake feed | The storage and candle rules behave as specified |
| `test_decode_real_format_frame` | Mocked frame with the real schema | Our decoder handles Yahoo's wire format |
| `real-unavailable-feed.png` | **Real** network failure (the dev sandbox blocks Yahoo, HTTP 403) | The unavailable state, error text and retry backoff on a genuine failure |
| Demo video | **Live Yahoo Finance** on the student's machine | The full path Yahoo → backend → SQLite → chart with live data |

## Manual checks (performed for the video)
1. Start with `./start.sh`. The feed goes from CONNECTING to LIVE, and the BTC-USD price flashes.
2. The data age stays a few seconds for crypto. For stocks outside 9:30–16:00 ET it grows, and the feed may show STALE once all symbols are silent.
3. Wait for a minute boundary. The provisional candle turns `✓ COMPLETE` and a new provisional candle starts.
4. Click **Simulate feed outage**. The pink banner and the UNAVAILABLE event appear, and the tick count stops increasing. Toggle it back and the feed returns to LIVE.
5. Click **Replay**. The REPLAY banner appears and the candles re-form from `candle_revisions`. **Back to live** returns to the live view.
6. Run `sqlite3 backend/data/market.db "SELECT COUNT(*) FROM observations"` and check that it grows.
