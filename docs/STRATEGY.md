# Strategy, simulated trading and backtesting (Part 4.2)

> Everything here is **simulated**. No order ever leaves the application.

## 1. Indicators — `backend/app/indicators.py`

| Name | Definition | Default |
|---|---|---|
| SMA(n) | The arithmetic mean of the **closes** of the last *n* candles. Undefined (`None`) for the first *n − 1* candles | fast **9**, slow **21** (`SMA_FAST`, `SMA_SLOW`) |
| diff | SMA_fast − SMA_slow | |

**Why 9/21:** these windows are a common short-term pair, and they were picked **before** looking at any results. They were not tuned on the data (see *overfitting* below). On 1-minute candles, a crossover is confirmed within minutes, so it can be observed live during a demo.

### Crossover rule
The detector remembers the sign of the last **non-zero** diff:
* **BUY** at bar *i* when that remembered sign was negative and diff(*i*) > 0 (the fast SMA crosses above the slow SMA).
* **SELL** at bar *i* when that remembered sign was positive and diff(*i*) < 0.
* A diff of exactly 0 is a *touch*, not a cross. It never signals and does not reset the remembered sign, so above → touch → above produces no signal.
* The first bar where both SMAs exist only initializes the sign.

Worked example (fast = 2, slow = 4; the same numbers are used in `tests/test_indicators.py` and `tests/test_backtest.py`):

| bar | 0 | 1 | 2 | 3 | 4 | 5 | 6 | 7 | 8 | 9 | 10 | 11 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| close | 10 | 10 | 10 | 10 | 9 | 8 | 12 | 14 | 13 | 9 | 7 | 6 |
| SMA2 | – | 10 | 10 | 10 | 9.5 | 8.5 | 10 | 13 | 13.5 | 11 | 8 | 6.5 |
| SMA4 | – | – | – | 10 | 9.75 | 9.25 | 9.75 | 10.75 | 11.75 | 12 | 10.75 | 8.75 |
| diff | | | | 0 | −0.25 | −0.75 | **+0.25** | +2.25 | +1.75 | **−1** | −2.75 | −2.25 |
| signal | | | | touch | init (bearish) | | **BUY** | | | **SELL** | | |

### Batch vs. incremental
* **Batch** (`sma_batch`, `crossover_signals`) computes over a whole list. The chart uses it, and the tests use it as a check.
* **Incremental** (`IncrementalSMA`, `CrossoverDetector`) processes one bar at a time with an O(1) rolling sum, re-summed every *n* bars to avoid float drift. The live bot and the backtest use it, so a decision can never see a later bar.
* The tests check that batch equals incremental, value by value and signal by signal, over 5,000 bars.

### Trusted reference
`sma_batch` is compared with **pandas** `Series.rolling(n).mean()` for n = 1, 2, 9, 21, 50 on 800-bar series, with a tolerance of 1e-9 (`test_sma_batch_matches_pandas_rolling_mean`).

### Unfinished (provisional) candles
The forming candle's close keeps changing, so a crossover that uses it can appear and then disappear.
* **Only completed candles** feed the strategy, in both the live bot and the backtest.
* For display only, `CrossoverDetector.peek(close)` shows what the SMAs and the signal **would** be if the forming candle closed now. The chart then shows a faded SMA point and a purple **`BUY? (provisional)`** circle, the legend says *"uses PROVISIONAL candle — not traded"*, and the Strategy panel shows a dashed *PROVISIONAL* box.
* A confirmed signal is drawn as a solid green ▲ BUY or pink ▼ SELL arrow.
* Late revisions of a candle that was already processed are stored by the 4.1 data layer, but they **do not re-run past decisions**. A decision is final once it is made, just as it would be for a real trader.

## 2. Simulated execution and accounting — `backend/app/broker.py`

| Assumption | Value |
|---|---|
| Starting cash | $100,000 (`STARTING_CASH`) |
| Direction | **Long-only**. BUY opens a position only when flat, and SELL closes the whole position. Other cases are stored as **skipped** orders with the reason |
| Order timing | The signal comes from the **close** of a completed candle. A market order is submitted as *pending* and **filled at the open of the next candle** of that symbol, never at the signal close, because that price was already gone when the signal existed |
| Slippage | 0.05% against us: buy at open × 1.0005, sell at open × 0.9995 (`SLIPPAGE`) |
| Commission | 0.10% of the fill notional on both legs (`FEE_RATE`) |
| Sizing | Each BUY spends **10% of current cash including the fee**: qty = 0.10 × cash / (price × 1.001) (`ALLOC`). Fractional quantities are allowed (natural for crypto, a simplification for stocks) |
| Cost basis | avg_cost = (price × qty + buy fee) / qty |
| Realized P/L (on SELL) | price × qty − sell fee − avg_cost × qty |
| Unrealized P/L | (mark − avg_cost) × qty, where mark = the latest tick (otherwise the latest stored close) |
| Identity checked | **equity − starting cash = realized + unrealized**, where equity = cash + Σ qty × mark |
| Not modelled | Margin, shorting, partial fills, market-hours checks for fills, order-book depth, taxes |

**Hand-checked examples** (`tests/test_broker.py`):
* No costs: buy 10% of $100,000 at 100 → 100 shares, cash $90,000. Mark 105 → equity $100,500. Sell at 110 → realized **+$1,000**, cash $101,000.
* With costs: buy at open 100 → fill 100.05, qty 99.8502, fee $9.99, cash exactly $90,000. Sell at open 110 → fill 109.945, realized **+$967.05**.
* A random 400-step trading run checks the accounting identity after every step.

## 3. Backtesting — `backend/app/backtest.py`

**Architecture: event-driven** (rather than vectorized). At each completed bar *i*, in time order:
1. fill the orders decided on earlier bars at bar *i*'s **open**;
2. reveal bar *i*'s **close** to the strategy, which may submit a new pending order;
3. mark the account to bar *i*'s close and record equity.

It reuses the **same** `CrossoverDetector` and `SimBroker` as the live bot (in an in-memory SQLite account). `test_live_bot_makes_exactly_the_backtest_trades` feeds the same candles to the live bot as open and complete events, and checks that it produces exactly the backtest's fills (same bars, prices and quantities).

**Data:** the completed candles stored in SQLite for the selected symbol and interval. That means the Yahoo history backfill (up to 2,000 bars) plus everything recorded live. Provisional candles are excluded, and their count is reported.

**Reported metrics:** total return; a buy-and-hold **benchmark with the same 10% sizing and costs**; the raw price change; maximum drawdown; round trips and win rate; fees; exposure (% of bars in a position); final equity; and an equity curve against the benchmark. Every run is saved in `backtest_runs`.

### What a backtest result establishes — and what it does not
* It **establishes** what these exact rules would have done on these exact stored candles, under the stated execution assumptions, with every decision limited to information available at that time.
* It does **not** establish future performance. In particular:
  * **Look-ahead bias** is prevented by construction and tested. `test_no_look_ahead_truncated_history_gives_identical_decisions` checks that a run on bars[:k] makes the same decisions as the first part of the full run, and `test_changing_the_future_cannot_change_past_decisions` changes later prices and checks that earlier decisions stay the same.
  * **Survivorship bias:** the universe (BTC, ETH, AAPL, TSLA, NVDA) was chosen today from instruments that exist and are popular now. Results say nothing about instruments that failed.
  * **Overfitting:** 9/21 was fixed in advance. The panel lets you try other windows, but picking the best window *after* seeing results would be overfitting, and a result found that way would have to be confirmed on new data.
  * The windows are **short** (hours to days of 1m/5m/15m candles from one regime), so the sample of trades is small. A handful of trades is not statistically meaningful.
  * Stock candles span overnight and weekend gaps. The SMA treats them as consecutive bars.
  * The fill model is optimistic for illiquid moments: no spread modelling beyond the fixed slippage.

## 4. Live bot — `backend/app/trader.py`
* It trades **1m completed candles** for all five symbols (`STRATEGY_INTERVAL`).
* On startup it is **primed** with the stored completed candles, without placing orders, so the SMAs are ready immediately.
* Candle events from the store work as follows: a candle that started after a pending order's signal bar → **fill** at its open. A candle that becomes complete and is newer than the last one processed → `CrossoverDetector.update` → maybe a **pending order**.
* The UI shows each order or fill as a pop-up, in the *Orders & fills* table and in the *Sim account* panel. `POST /api/account/reset` restarts the account.
