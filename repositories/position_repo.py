"""Position-manager persistence helpers."""

from __future__ import annotations

from typing import Any

from db import DB_PATH, get_connection
from repositories.trade_accounting import fill_bearing_order_condition


def entry_context_rows(symbol: str, db_path=DB_PATH):
    fill_bearing = fill_bearing_order_condition()
    with get_connection(db_path) as con:
        return con.execute(
            f"""
            SELECT
                timestamp, symbol, action, qty, fill_price,
                market_bias, market_bias_effective,
                trend_direction, trend_strength,
                momentum_direction, momentum_pct,
                session_trend_label, session_trend_score,
                prediction_score, prediction_decision,
                setup_label, setup_policy_action,
                buy_opportunity_score, buy_opportunity_recommendation,
                ml_prediction_score, ml_prediction_bucket
            FROM trades
            WHERE symbol = ?
              AND approved = 1
              AND {fill_bearing}
              AND qty IS NOT NULL
              AND fill_price IS NOT NULL
              AND action IN ('buy', 'sell')
            ORDER BY timestamp ASC, id ASC
            """,
            (symbol,),
        ).fetchall()


def insert_position_manager_exit(
    *,
    timestamp: str,
    symbol: str | None,
    signal_price: Any,
    reason: str,
    confidence: str,
    order_id: str | None,
    order_status: str | None,
    qty: int | None,
    entry_context: dict[str, Any],
    momentum_direction: str,
    momentum_pct: Any,
    db_path=DB_PATH,
) -> None:
    with get_connection(db_path) as con:
        con.execute(
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
                fill_price,

                market_bias,
                market_bias_effective,
                trend_direction,
                trend_strength,
                momentum_direction,
                momentum_pct,
                session_trend_label,
                session_trend_score,
                prediction_score,
                prediction_decision,
                setup_label,
                setup_policy_action,
                buy_opportunity_score,
                buy_opportunity_recommendation
            ) VALUES (?, ?, 'sell', ?, 1, ?, ?, 0.0, 0.0, 0.0, ?, ?, ?, NULL,
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                symbol,
                signal_price,
                reason,
                confidence,
                order_id,
                order_status,
                qty,
                entry_context.get("entry_market_bias"),
                entry_context.get("entry_market_bias_effective"),
                (entry_context.get("entry_trend") or "/").split("/")[0],
                (entry_context.get("entry_trend") or "/").split("/")[1],
                momentum_direction,
                momentum_pct,
                entry_context.get("entry_session_trend_label"),
                entry_context.get("entry_session_trend_score"),
                entry_context.get("entry_prediction_score"),
                entry_context.get("entry_prediction_decision"),
                entry_context.get("entry_setup_label"),
                entry_context.get("entry_setup_policy_action"),
                entry_context.get("entry_buy_opportunity_score"),
                entry_context.get("entry_buy_opportunity_recommendation"),
            ),
        )
