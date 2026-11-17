"""Event-driven backtest of the SMA crossover strategy.

The loop processes one COMPLETED candle at a time, in time order, and at bar i does exactly:

  1. fill orders created at earlier bars, at bar i's OPEN (+/- slippage, + commission)
  2. reveal bar i's CLOSE to the strategy -> it may emit BUY/SELL -> a PENDING order is submitted
  3. mark the account to bar i's close and record equity

So a decision made at bar i can only use closes 0..i, and it is executed at the open of bar i+1:
no look-ahead. tests/test_backtest.py proves it by checking that running on a truncated history
produces exactly the same decisions as the prefix of the full run.

It reuses the same CrossoverDetector and SimBroker as the live bot (an in-memory SQLite account),
so live and backtest behaviour cannot drift apart.
"""
from __future__ import annotations

import json
import sqlite3
from typing import Optional

from .broker import BrokerConfig, SimBroker
from .indicators import CrossoverDetector


def run_backtest(candles: list[dict], symbol: str, interval: str, fast: int, slow: int,
                 cfg: BrokerConfig = BrokerConfig()) -> dict:
    bars = [c for c in candles if c.get("is_complete", True)]
    bars.sort(key=lambda c: c["time"])
    mem = sqlite3.connect(":memory:")
    mem.row_factory = sqlite3.Row
    broker = SimBroker(mem, "backtest", cfg, kind="backtest", commit=False)
    det = CrossoverDetector(fast, slow)

    equity_curve, signals = [], []
    peak, max_dd = cfg.starting_cash, 0.0
    in_pos_bars = 0
    bh_qty: Optional[float] = None
    bh_cash = cfg.starting_cash

    for i, c in enumerate(bars):
        t = c["time"]
        # 1) execute what was decided on earlier bars, at this bar's open
        broker.fill_pending(symbol, t, c["open"], t * 1000)
        if bh_qty is None:  # benchmark: buy & hold with the SAME sizing and costs, entered at bar 0 open
            px = c["open"] * (1 + cfg.slippage)
            bh_qty = cfg.alloc * bh_cash / (px * (1 + cfg.fee_rate))
            bh_cash -= px * bh_qty * (1 + cfg.fee_rate)
        # 2) the bar closes: the strategy sees only this close
        f, s, sig = det.update(c["close"])
        if sig:
            order = broker.submit(symbol, sig, t, c["close"],
                                  f"SMA {fast}/{slow} cross {'up' if sig == 'BUY' else 'down'} on completed {interval} candle",
                                  t * 1000, f, s)
            signals.append({"time": t, "signal": sig, "close": c["close"], "sma_fast": f, "sma_slow": s,
                            "order_status": order["status"], "note": order["note"]})
        # 3) mark to market at this close
        pos = broker.position(symbol)
        cash = broker.cash
        equity = cash + (pos["qty"] * c["close"] if pos else 0.0)
        in_pos_bars += 1 if pos else 0
        peak = max(peak, equity)
        max_dd = max(max_dd, (peak - equity) / peak if peak else 0.0)
        bench = bh_cash + bh_qty * c["close"]
        equity_curve.append({"time": t, "equity": round(equity, 4), "benchmark": round(bench, 4)})

    snap = broker.snapshot({symbol: bars[-1]["close"]} if bars else {}, limit=10_000)
    fills = [dict(r) for r in mem.execute("SELECT * FROM sim_fills ORDER BY id")]
    pending = [dict(r) for r in mem.execute("SELECT * FROM sim_orders WHERE status='pending'")]
    sells = [f for f in fills if f["side"] == "SELL"]
    wins = sum(1 for f in sells if f["realized_pnl"] > 0)
    final_equity = snap["equity"]
    metrics = {
        "bars": len(bars),
        "first_bar": bars[0]["time"] if bars else None,
        "last_bar": bars[-1]["time"] if bars else None,
        "signals": len(signals),
        "fills": len(fills),
        "round_trips": len(sells),
        "wins": wins,
        "win_rate_pct": (100 * wins / len(sells)) if sells else None,
        "final_equity": final_equity,
        "total_return_pct": (final_equity / cfg.starting_cash - 1) * 100,
        "benchmark_return_pct": ((equity_curve[-1]["benchmark"] / cfg.starting_cash - 1) * 100) if bars else 0.0,
        "price_change_pct": ((bars[-1]["close"] / bars[0]["open"] - 1) * 100) if bars else 0.0,
        "max_drawdown_pct": max_dd * 100,
        "exposure_pct": (100 * in_pos_bars / len(bars)) if bars else 0.0,
        "realized_pnl": snap["realized_pnl"],
        "unrealized_pnl": snap["unrealized_pnl"],
        "fees": snap["fees"],
        "open_position": snap["positions"][0] if snap["positions"] else None,
        "pending_at_end": len(pending),
        "warmup_bars": slow - 1,
    }
    trades = [{"time": f["fill_bar"], "side": f["side"], "qty": f["qty"], "ref_price": f["ref_price"],
               "fill_price": f["fill_price"], "fee": f["fee"], "realized_pnl": f["realized_pnl"],
               "cash_after": f["cash_after"]} for f in fills]
    mem.close()
    return {"symbol": symbol, "interval": interval, "fast": fast, "slow": slow,
            "config": {"starting_cash": cfg.starting_cash, "fee_rate": cfg.fee_rate,
                       "slippage": cfg.slippage, "alloc": cfg.alloc},
            "metrics": metrics, "signals": signals, "trades": trades, "equity": equity_curve}


def save_run(conn: sqlite3.Connection, result: dict, created_ms: int) -> int:
    m = result["metrics"]
    cur = conn.execute(
        "INSERT INTO backtest_runs(created_ms, symbol, interval, fast, slow, bars, first_bar, last_bar,"
        " params_json, metrics_json, trades_json, equity_json) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
        (created_ms, result["symbol"], result["interval"], result["fast"], result["slow"], m["bars"],
         m["first_bar"], m["last_bar"], json.dumps(result["config"]), json.dumps(m),
         json.dumps(result["trades"]), json.dumps(result["equity"])))
    conn.commit()
    return cur.lastrowid
