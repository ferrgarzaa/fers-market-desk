"""Simulated broker / account. NOTHING here talks to a real brokerage.

Execution assumptions (also in docs/STRATEGY.md)
------------------------------------------------
* Long-only. A BUY signal opens a position only when flat; a SELL signal closes the whole position.
  Other cases are recorded as SKIPPED orders with the reason (e.g. "no position to sell").
* Signals are produced on the CLOSE of a completed candle. The resulting market order is
  submitted as PENDING and filled at the OPEN of the next candle of that symbol (never at the
  close that produced the signal — that price was already gone when the signal existed).
* Slippage: buys fill at open * (1 + slippage), sells at open * (1 - slippage).
* Commission: fee_rate * fill notional, paid in cash on both legs.
* Sizing: a BUY spends `alloc` (default 10 %) of current cash, INCLUDING its commission:
  qty = alloc * cash / (fill_price * (1 + fee_rate)). Fractional quantities are allowed
  (crypto trades in fractions; for stocks this is a simplification).
* Cost basis includes the buy commission: avg_cost = (fill_price*qty + fee) / qty.
  Therefore, at every moment:  equity = cash + sum(qty * mark)
                               equity - starting_cash = realized_pnl + unrealized_pnl
  realized_pnl (on a sell)   = fill_price*qty - sell_fee - avg_cost*qty
  unrealized_pnl             = (mark - avg_cost) * qty
  The identity is checked in tests/test_broker.py.
* No margin, no shorting, no partial fills, no market-hours check on fills.
"""
from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Optional

SCHEMA = """
CREATE TABLE IF NOT EXISTS sim_accounts (
    account_id     TEXT PRIMARY KEY,          -- 'live' or 'bt-<run id>'
    kind           TEXT NOT NULL,             -- live | backtest
    starting_cash  REAL NOT NULL,
    cash           REAL NOT NULL,
    fee_rate       REAL NOT NULL,
    slippage       REAL NOT NULL,
    alloc          REAL NOT NULL,
    created_ms     INTEGER NOT NULL,
    params_json    TEXT
);
CREATE TABLE IF NOT EXISTS sim_positions (
    account_id TEXT NOT NULL, symbol TEXT NOT NULL,
    qty REAL NOT NULL, avg_cost REAL NOT NULL, opened_bar INTEGER,
    PRIMARY KEY (account_id, symbol)
);
CREATE TABLE IF NOT EXISTS sim_orders (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    TEXT NOT NULL,
    symbol        TEXT NOT NULL,
    side          TEXT NOT NULL,              -- BUY | SELL
    status        TEXT NOT NULL,              -- pending | filled | skipped
    reason        TEXT NOT NULL,              -- e.g. 'SMA 9/21 cross up on completed 1m candle'
    signal_bar    INTEGER NOT NULL,           -- bucket_start of the candle whose close produced it
    signal_close  REAL NOT NULL,
    sma_fast REAL, sma_slow REAL,
    created_ms    INTEGER NOT NULL,
    filled_ms     INTEGER,
    note          TEXT
);
CREATE INDEX IF NOT EXISTS ix_orders_acct ON sim_orders(account_id, id);
CREATE TABLE IF NOT EXISTS sim_fills (
    id            INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id    TEXT NOT NULL,
    order_id      INTEGER NOT NULL REFERENCES sim_orders(id),
    symbol        TEXT NOT NULL,
    side          TEXT NOT NULL,
    qty           REAL NOT NULL,
    ref_price     REAL NOT NULL,              -- open of the fill candle
    fill_price    REAL NOT NULL,              -- after slippage
    fee           REAL NOT NULL,
    fill_bar      INTEGER NOT NULL,           -- bucket_start of the fill candle
    realized_pnl  REAL NOT NULL DEFAULT 0,
    cash_after    REAL NOT NULL,
    time_ms       INTEGER NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_fills_acct ON sim_fills(account_id, id);
CREATE TABLE IF NOT EXISTS backtest_runs (
    id           INTEGER PRIMARY KEY AUTOINCREMENT,
    created_ms   INTEGER NOT NULL,
    symbol       TEXT NOT NULL, interval TEXT NOT NULL,
    fast INTEGER NOT NULL, slow INTEGER NOT NULL,
    bars         INTEGER NOT NULL,
    first_bar    INTEGER, last_bar INTEGER,
    params_json  TEXT NOT NULL,
    metrics_json TEXT NOT NULL,
    trades_json  TEXT NOT NULL,
    equity_json  TEXT NOT NULL
);
"""


@dataclass
class BrokerConfig:
    starting_cash: float = 100_000.0
    fee_rate: float = 0.001      # 0.10 %
    slippage: float = 0.0005     # 0.05 %
    alloc: float = 0.10          # 10 % of cash per BUY


class SimBroker:
    def __init__(self, conn: sqlite3.Connection, account_id: str, cfg: BrokerConfig = BrokerConfig(),
                 kind: str = "live", params: Optional[dict] = None, now_ms: int = 0, commit: bool = True):
        self.conn, self.account_id, self.cfg, self._commit = conn, account_id, cfg, commit
        conn.executescript(SCHEMA)
        row = conn.execute("SELECT * FROM sim_accounts WHERE account_id=?", (account_id,)).fetchone()
        if row is None:
            conn.execute(
                "INSERT INTO sim_accounts(account_id, kind, starting_cash, cash, fee_rate, slippage, alloc,"
                " created_ms, params_json) VALUES (?,?,?,?,?,?,?,?,?)",
                (account_id, kind, cfg.starting_cash, cfg.starting_cash, cfg.fee_rate, cfg.slippage,
                 cfg.alloc, now_ms, json.dumps(params or {})))
            self._maybe_commit()
        else:  # an existing account keeps the settings it was created with
            self.cfg = BrokerConfig(row["starting_cash"], row["fee_rate"], row["slippage"], row["alloc"])

    def _maybe_commit(self):
        if self._commit:
            self.conn.commit()

    # ------------------------------------------------------------------ state
    @property
    def cash(self) -> float:
        return self.conn.execute("SELECT cash FROM sim_accounts WHERE account_id=?",
                                 (self.account_id,)).fetchone()[0]

    def position(self, symbol: str) -> Optional[dict]:
        r = self.conn.execute("SELECT * FROM sim_positions WHERE account_id=? AND symbol=?",
                              (self.account_id, symbol)).fetchone()
        return dict(r) if r else None

    def positions(self) -> list[dict]:
        return [dict(r) for r in self.conn.execute(
            "SELECT * FROM sim_positions WHERE account_id=? ORDER BY symbol", (self.account_id,))]

    # ------------------------------------------------------------------ orders
    def submit(self, symbol: str, side: str, signal_bar: int, signal_close: float, reason: str,
               created_ms: int, sma_fast: Optional[float] = None, sma_slow: Optional[float] = None) -> dict:
        pos = self.position(symbol)
        pending = self.conn.execute(
            "SELECT 1 FROM sim_orders WHERE account_id=? AND symbol=? AND status='pending'",
            (self.account_id, symbol)).fetchone()
        status, note = "pending", None
        if pending:
            status, note = "skipped", "another order for this symbol is still pending"
        elif side == "BUY" and pos:
            status, note = "skipped", "already long (long-only, one position per symbol)"
        elif side == "SELL" and not pos:
            status, note = "skipped", "no position to sell (long-only, no shorting)"
        cur = self.conn.execute(
            "INSERT INTO sim_orders(account_id, symbol, side, status, reason, signal_bar, signal_close,"
            " sma_fast, sma_slow, created_ms, note) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (self.account_id, symbol, side, status, reason, signal_bar, signal_close, sma_fast, sma_slow,
             created_ms, note))
        self._maybe_commit()
        return self._order(cur.lastrowid)

    def _order(self, oid: int) -> dict:
        return dict(self.conn.execute("SELECT * FROM sim_orders WHERE id=?", (oid,)).fetchone())

    def fill_pending(self, symbol: str, bar_time: int, bar_open: float, time_ms: int) -> list[dict]:
        """Fill pending orders of `symbol` at the open of a candle that started AFTER the signal candle."""
        rows = self.conn.execute(
            "SELECT * FROM sim_orders WHERE account_id=? AND symbol=? AND status='pending' AND signal_bar<? "
            "ORDER BY id", (self.account_id, symbol, bar_time)).fetchall()
        fills = []
        for o in rows:
            fills.append(self._fill(dict(o), bar_time, bar_open, time_ms))
        if fills:
            self._maybe_commit()
        return fills

    def _fill(self, o: dict, bar_time: int, bar_open: float, time_ms: int) -> dict:
        c = self.cfg
        cash = self.cash
        sym = o["symbol"]
        realized = 0.0
        if o["side"] == "BUY":
            px = bar_open * (1 + c.slippage)
            qty = c.alloc * cash / (px * (1 + c.fee_rate))
            fee = px * qty * c.fee_rate
            cash -= px * qty + fee
            self.conn.execute(
                "INSERT INTO sim_positions(account_id, symbol, qty, avg_cost, opened_bar) VALUES (?,?,?,?,?)",
                (self.account_id, sym, qty, (px * qty + fee) / qty, bar_time))
        else:
            pos = self.position(sym)
            px = bar_open * (1 - c.slippage)
            qty = pos["qty"]
            fee = px * qty * c.fee_rate
            realized = px * qty - fee - pos["avg_cost"] * qty
            cash += px * qty - fee
            self.conn.execute("DELETE FROM sim_positions WHERE account_id=? AND symbol=?",
                              (self.account_id, sym))
        self.conn.execute("UPDATE sim_accounts SET cash=? WHERE account_id=?", (cash, self.account_id))
        cur = self.conn.execute(
            "INSERT INTO sim_fills(account_id, order_id, symbol, side, qty, ref_price, fill_price, fee, fill_bar,"
            " realized_pnl, cash_after, time_ms) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (self.account_id, o["id"], sym, o["side"], qty, bar_open, px, fee, bar_time, realized, cash, time_ms))
        self.conn.execute("UPDATE sim_orders SET status='filled', filled_ms=? WHERE id=?", (time_ms, o["id"]))
        f = dict(self.conn.execute("SELECT * FROM sim_fills WHERE id=?", (cur.lastrowid,)).fetchone())
        f["reason"] = o["reason"]
        return f

    def reset(self, now_ms: int):
        for t in ("sim_positions", "sim_fills", "sim_orders"):
            self.conn.execute(f"DELETE FROM {t} WHERE account_id=?", (self.account_id,))
        self.conn.execute("UPDATE sim_accounts SET cash=starting_cash, created_ms=? WHERE account_id=?",
                          (now_ms, self.account_id))
        self.conn.commit()

    # ------------------------------------------------------------------ reporting
    def snapshot(self, marks: dict[str, float], limit: int = 30) -> dict:
        cash = self.cash
        positions = []
        unreal = 0.0
        for p in self.positions():
            mark = marks.get(p["symbol"], p["avg_cost"])
            u = (mark - p["avg_cost"]) * p["qty"]
            unreal += u
            positions.append({**p, "mark": mark, "market_value": mark * p["qty"], "unrealized_pnl": u})
        agg = self.conn.execute(
            "SELECT COALESCE(SUM(realized_pnl),0), COALESCE(SUM(fee),0), COUNT(*) FROM sim_fills WHERE account_id=?",
            (self.account_id,)).fetchone()
        equity = cash + sum(p["market_value"] for p in positions)
        orders = [dict(r) for r in self.conn.execute(
            "SELECT o.*, f.fill_price, f.qty AS fill_qty, f.fee, f.realized_pnl, f.fill_bar "
            "FROM sim_orders o LEFT JOIN sim_fills f ON f.order_id=o.id "
            "WHERE o.account_id=? ORDER BY o.id DESC LIMIT ?", (self.account_id, limit))]
        return {"account_id": self.account_id, "starting_cash": self.cfg.starting_cash, "cash": cash,
                "equity": equity, "realized_pnl": agg[0], "unrealized_pnl": unreal, "fees": agg[1],
                "fills": agg[2], "return_pct": (equity / self.cfg.starting_cash - 1) * 100,
                "positions": positions, "orders": orders,
                "config": {"fee_rate": self.cfg.fee_rate, "slippage": self.cfg.slippage, "alloc": self.cfg.alloc}}
