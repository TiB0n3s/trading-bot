"""Fill stream persistence helpers."""

from __future__ import annotations

from datetime import datetime
import json
from typing import Any

from db import DB_PATH, get_connection


def init_fill_events_table(db_path=DB_PATH) -> None:
    with get_connection(db_path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS fill_events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                event TEXT,
                order_id TEXT,
                parent_order_id TEXT,
                client_order_id TEXT,
                symbol TEXT,
                side TEXT,
                status TEXT,
                filled_qty REAL,
                fill_price REAL,
                raw_json TEXT
            )
            """
        )


def table_exists(table_name: str, db_path=DB_PATH) -> bool:
    with get_connection(db_path) as con:
        row = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
    return row is not None


def trade_order_field_summary(target_date: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT
                COUNT(*) AS approved_rows,
                SUM(CASE WHEN order_id IS NOT NULL AND order_id != '' THEN 1 ELSE 0 END) AS with_order_id,
                SUM(CASE WHEN order_id IS NULL OR order_id = '' THEN 1 ELSE 0 END) AS missing_order_id,
                SUM(CASE WHEN order_status IS NULL OR order_status = '' THEN 1 ELSE 0 END) AS missing_order_status
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND approved = 1
            """,
            (target_date,),
        ).fetchone()


def trade_order_status_rows(target_date: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT COALESCE(order_status, 'missing') AS order_status, COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND approved = 1
            GROUP BY COALESCE(order_status, 'missing')
            ORDER BY n DESC, order_status
            """,
            (target_date,),
        ).fetchall()


def recent_approved_order_rows(target_date: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT timestamp, symbol, action, order_id, order_status, qty, fill_price,
                   position_size_pct, stop_loss_pct, take_profit_pct
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND approved = 1
            ORDER BY timestamp DESC, id DESC
            LIMIT 12
            """,
            (target_date,),
        ).fetchall()


def fill_event_summary_rows(target_date: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT COALESCE(event, 'missing') AS event,
                   COALESCE(status, 'missing') AS status,
                   COUNT(*) AS n
            FROM fill_events
            WHERE substr(timestamp, 1, 10) = ?
            GROUP BY COALESCE(event, 'missing'), COALESCE(status, 'missing')
            ORDER BY n DESC, event, status
            """,
            (target_date,),
        ).fetchall()


def external_alpaca_order_summary_rows(target_date: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT COALESCE(status, 'missing') AS status,
                   COALESCE(side, 'missing') AS side,
                   COUNT(*) AS n
            FROM external_alpaca_orders
            WHERE substr(COALESCE(submitted_at, imported_at), 1, 10) = ?
            GROUP BY COALESCE(status, 'missing'), COALESCE(side, 'missing')
            ORDER BY n DESC, status, side
            """,
            (target_date,),
        ).fetchall()


def record_fill_event(event: str, order: Any, db_path=DB_PATH) -> None:
    order_id = order.get("id")
    parent_order_id = order.get("parent_order_id")
    client_order_id = order.get("client_order_id")
    symbol = order.get("symbol")
    side = order.get("side")
    status = order.get("status")
    filled_qty = order.get("filled_qty")
    fill_price = order.get("filled_avg_price")

    try:
        raw_json = json.dumps(dict(order))
    except Exception:
        raw_json = str(order)

    with get_connection(db_path) as con:
        con.execute(
            """
            INSERT INTO fill_events (
                timestamp, event, order_id, parent_order_id, client_order_id,
                symbol, side, status, filled_qty, fill_price, raw_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                event,
                order_id,
                parent_order_id,
                client_order_id,
                symbol,
                side,
                status,
                float(filled_qty) if filled_qty else None,
                float(fill_price) if fill_price else None,
                raw_json,
            ),
        )


def update_trade_fill(
    order_id: str,
    status: str,
    fill_price: float | None,
    filled_qty: float | None = None,
    db_path=DB_PATH,
) -> int:
    qty = int(float(filled_qty)) if filled_qty not in (None, "") else None
    with get_connection(db_path) as con:
        cur = con.execute(
            """
            UPDATE trades
            SET order_status = ?,
                fill_price = COALESCE(?, fill_price),
                qty = COALESCE(?, qty)
            WHERE order_id = ?
            """,
            (status, fill_price, qty, order_id),
        )
        return int(cur.rowcount)


def trades_missing_confirmed_fills(db_path=DB_PATH) -> list[Any]:
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT id, timestamp, symbol, action, qty, signal_price, order_id, order_status
            FROM trades
            WHERE approved = 1
              AND action IN ('buy', 'sell')
              AND qty IS NOT NULL
              AND fill_price IS NULL
              AND order_id IS NOT NULL
              AND order_id NOT LIKE 'reconcile_%'
            ORDER BY timestamp ASC
            """
        ).fetchall()


def update_trade_fill_by_row_id(
    *,
    row_id: int,
    status: str,
    fill_price: float,
    db_path=DB_PATH,
) -> int:
    with get_connection(db_path) as con:
        cur = con.execute(
            "UPDATE trades SET order_status = ?, fill_price = ? WHERE id = ?",
            (status, fill_price, row_id),
        )
        return int(cur.rowcount)


def pending_trade_orders(
    statuses: tuple[str, ...],
    db_path=DB_PATH,
) -> list[Any]:
    placeholders = ", ".join(["?"] * len(statuses))
    with get_connection(db_path) as con:
        return con.execute(
            f"SELECT id, order_id, symbol FROM trades WHERE order_status IN ({placeholders})",
            statuses,
        ).fetchall()


def trade_status_by_id(trade_id: int, db_path=DB_PATH) -> Any:
    with get_connection(db_path) as con:
        return con.execute(
            "SELECT order_status, fill_price FROM trades WHERE id = ?",
            (trade_id,),
        ).fetchone()


def update_trade_status_by_id(
    *,
    trade_id: int,
    status: str,
    fill_price: float | None,
    db_path=DB_PATH,
) -> int:
    with get_connection(db_path) as con:
        cur = con.execute(
            "UPDATE trades SET order_status = ?, fill_price = ? WHERE id = ?",
            (status, fill_price, trade_id),
        )
        return int(cur.rowcount)


def trade_order_exists(order_id: str, db_path=DB_PATH) -> bool:
    if not order_id:
        return False

    with get_connection(db_path) as con:
        row = con.execute(
            "SELECT id FROM trades WHERE order_id = ? LIMIT 1",
            (order_id,),
        ).fetchone()
        return row is not None


def insert_synthetic_exit(
    *,
    order_id: str,
    symbol: str,
    side: str,
    status: str,
    filled_qty: float | str | None,
    fill_price: float | None,
    parent_order_id: str | None = None,
    db_path=DB_PATH,
) -> bool:
    action = "sell" if side == "sell" else "buy"

    if trade_order_exists(order_id, db_path=db_path):
        return False

    with get_connection(db_path) as con:
        con.execute(
            """
            INSERT INTO trades (
                timestamp, symbol, action, signal_price, approved, rejection_reason,
                confidence, position_size_pct, stop_loss_pct, take_profit_pct,
                order_id, order_status, qty, fill_price
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                symbol,
                action,
                fill_price,
                1,
                f"synthetic_bracket_exit: parent_order_id={parent_order_id}"
                if parent_order_id
                else "synthetic_bracket_exit: parent unknown",
                "n/a",
                0.0,
                0.0,
                0.0,
                order_id,
                status,
                int(float(filled_qty)) if filled_qty else None,
                fill_price,
            ),
        )
        return True
