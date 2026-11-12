# Instructions for coding agents

This repository is a course project (IST 402, Assignment 4). It is built in cumulative parts: 4.1 dashboard → 4.2 indicators, simulated trading and backtesting → 4.3 AI decisions, chat, vision and audio.

## Ground rules
* **All trading is simulated.** Never add code that places real orders or stores brokerage credentials.
* **No secrets in git.** Model or API keys (Part 4.3) go in `.env`, which git ignores, and are read through `os.getenv`. Document the variable names in the README, never their values.
* **Live data path is Yahoo Finance** (`FEED_MODE=yahoo`). `FEED_MODE=fake` exists only for tests, and the UI must keep labelling it FAKE.
* **Persist before broadcast.** Every observation goes through `CandleStore` (SQLite) before it reaches a browser.
* **Never overwrite history silently.** Candle changes must bump `revision` and append to `candle_revisions`.
* **Provisional ≠ complete.** Anything that computes signals must state whether it used the provisional candle. Confirmed signals use complete candles only.
* Keep the docs describing the system **that exists**: update `docs/` and the README in the same commit as a behaviour change.

## Layout
```
backend/app/config.py   env-driven settings
backend/app/db.py       schema + connect()
backend/app/store.py    CandleStore: identity, duplicates, revisions, out-of-order, completion, queries
backend/app/feed.py     YahooFeed (live), FakeFeed (tests), history backfill
backend/app/main.py     FastAPI app, Hub (WS clients, clock loop, replay), REST endpoints
backend/tests/          pytest (store rules, feed decoding and failure, API end to end)
frontend/src/store.js   reactive state + browser WebSocket
frontend/src/components ChartPanel (lightweight-charts v5), panels
frontend/e2e/           Playwright browser test
docs/                   data flow, schema, design, verification, evidence screenshots
```

## Before committing
```bash
cd backend && python -m pytest -q
cd frontend && npm run build && npx playwright test
```
Both run in GitHub Actions on every push.

## Style
* Python: type hints, small functions, docstrings that state the *rule*, not just what the code does.
* Vue: `<script setup>`; colours come from the CSS variables in `src/style.css` (purple/pink theme chosen by the student). Keep the JetBrains Mono terminal look.
