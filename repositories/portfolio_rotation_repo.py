"""Portfolio rotation persistence helpers."""

from __future__ import annotations

from typing import Any

from db import DB_PATH, get_connection


def recent_buy_signals(since_timestamp: str, limit: int = 300, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT
                id,
                timestamp,
                symbol,
                action,
                signal_price,
                approved,
                rejection_reason,

                market_bias,
                market_bias_effective,
                fundamental_score,
                risk_level,
                entry_quality,
                trend_direction,
                trend_strength,
                momentum_direction,
                momentum_pct,

                session_trend_label,
                session_trend_score,
                session_return_pct,
                session_momentum_5m_pct,
                session_momentum_15m_pct,
                session_momentum_30m_pct,
                session_distance_from_vwap_pct,

                prediction_score,
                prediction_decision,

                setup_label,
                setup_policy_action,
                setup_size_multiplier,

                buy_opportunity_score,
                buy_opportunity_recommendation,
                buy_opportunity_reason
            FROM trades
            WHERE LOWER(action) = 'buy'
              AND timestamp >= ?
              AND signal_price IS NOT NULL
            ORDER BY id DESC
            LIMIT ?
            """,
            (since_timestamp, limit),
        ).fetchall()


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
