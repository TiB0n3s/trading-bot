"""Portfolio rotation persistence helpers."""

from __future__ import annotations

from typing import Any

from db import DB_PATH, get_connection


def insert_rotation_sell(
    *,
    timestamp: str,
    decision: dict[str, Any],
    order: dict[str, Any],
    db_path=DB_PATH,
) -> int | None:
    order_id = order.get("order_id") if isinstance(order, dict) else None
    if not order_id:
        return None

    with get_connection(db_path) as con:
        existing = con.execute(
            "SELECT id FROM trades WHERE order_id = ? LIMIT 1",
            (order_id,),
        ).fetchone()
        if existing:
            return int(existing["id"])

        cur = con.execute(
            """
            INSERT INTO trades (
                timestamp,
                symbol,
                action,
                signal_price,
                approved,
                rejection_reason,
                confidence,
                position_size_pct,
                stop_loss_pct,
                take_profit_pct,
                order_id,
                order_status,
                qty,
                fill_price
            ) VALUES (?, ?, 'sell', ?, 1, ?, ?, 0.0, 0.0, 0.0, ?, ?, ?, NULL)
            """,
            (
                timestamp,
                decision.get("symbol_to_sell"),
                order.get("current_price"),
                "portfolio_rotation_manager: live replacement sell submitted; "
                + str(decision.get("reason") or ""),
                "portfolio_rotation_manager",
                order_id,
                order.get("status") or "submitted",
                int(float(order.get("qty"))) if order.get("qty") is not None else None,
            ),
        )
        return int(cur.lastrowid)
