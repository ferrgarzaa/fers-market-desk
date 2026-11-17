# Tool and model disclosure

| Tool / model | Used for | Notes |
|---|---|---|
| **Claude (Anthropic), model Claude Opus 5.5**, in the Claude app's agent workspace | Generating the backend, frontend, tests, CI workflow and first drafts of the docs; running the tests and the browser checks in its sandbox; pushing to GitHub | The student directed the work. Before any code was written, the agent asked a series of design questions and the student chose every UI decision: the dark purple/pink theme, the instruments (crypto + stocks), the Bloomberg-terminal layout, the 1m/5m/15m selector, the app name "Fer's Market Desk", JetBrains Mono, and the extras (ticker tape, price flash, dashed provisional candle, ET clock and market status). The student also chose to keep every candle revision and to write the report in English |
| Claude (same session), using the Claude desktop app's browser pane on my laptop | Capturing the demo-video screenshots from my running app (live Yahoo data) and assembling them with captions using ffmpeg | I started the app myself; the agent clicked through the demo (outage, replay) and added the captions |
| Playwright + Google Chrome | Browser tests and screenshots | — |
| GitHub Actions | Runs pytest, the frontend build and the Playwright test on every push | — |

## Where the choice of tool or approach changed, and why
* The original plan was to use `yfinance.AsyncWebSocket.listen()` directly. Reading its source showed that it retries internally and hides exceptions by default (`YfConfig.debug.hide_exceptions=True`), so the app could not report UNAVAILABLE or explain why. It was **revised** to use our own `websockets` loop with yfinance's protobuf schema (see EVIDENCE-LOG entry 1).
* Yahoo is blocked inside the agent's sandbox, so live verification was moved to the student's machine (the video). The sandbox failure was kept as evidence of a real unavailable feed.

## Ownership
The student reviewed the generated code, ran it locally against live Yahoo data, and can explain the data path and the duplicate, revision and out-of-order rules (docs/DATA_FLOW.md).

## Part 4.2
| Tool / model | Used for |
|---|---|
| **Claude Opus 5.5** (same agent workspace) | Generated `indicators.py`, `broker.py`, `trader.py` and `backtest.py`, the new Vue panels, 30 new tests and the docs (STRATEGY.md). It also ran the tests and browser checks in its sandbox and pushed to GitHub |

**Choices I made before any code was written** (the agent asked; I chose): SMA **9/21**; **$100,000** starting cash with **10% of cash per trade**; **commission + slippage** (0.10% / 0.05%, fill at the next candle's open); and **everything on one screen** rather than tabs.

**Where the approach changed and why:**
* A hand-calculated expected value in an accounting test was wrong. The test exposed it, and the formula check confirmed the code (EVIDENCE-LOG #7).
* The browser tests were made independent of tab state and of earlier runs (EVIDENCE-LOG #8).
* The trusted reference for the SMA is pandas `rolling().mean()`, which was already installed as a yfinance dependency, so no new library was added.
