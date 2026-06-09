"""Portfolio rotation persistence helpers."""

from __future__ import annotations

from typing import Any

from db import DB_PATH, get_connection


def _table_exists(con, table_name: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table_name,),
    ).fetchone()
    return row is not None


def recent_buy_signals(since_timestamp: str, limit: int = 300, db_path=DB_PATH):
    with get_connection(db_path) as con:
        trade_rows = con.execute(
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
                buy_opportunity_reason,
                NULL AS live_feedback_status,
                NULL AS live_feedback_penalty
            FROM trades
            WHERE LOWER(action) = 'buy'
              AND timestamp >= ?
              AND signal_price IS NOT NULL
            ORDER BY id DESC
            LIMIT ?
            """,
            (since_timestamp, limit),
        ).fetchall()

        auto_rows = []
        if _table_exists(con, "auto_buy_candidates"):
            live_block_expr = "NULL"
            risk_cross_check_expr = "NULL"
            prediction_score_expr = "NULL"
            prediction_decision_expr = "NULL"
            live_feedback_status_expr = "NULL"
            live_feedback_penalty_expr = "NULL"
            if _table_exists(con, "auto_buy_decision_snapshots"):
                live_block_expr = """
                    (
                        SELECT ads.live_block_reason
                        FROM auto_buy_decision_snapshots ads
                        WHERE ads.symbol = abc.symbol
                          AND ads.candidate_timestamp = abc.timestamp
                        ORDER BY ads.id DESC
                        LIMIT 1
                    )
                """
                risk_cross_check_expr = """
                    (
                        SELECT ads.risk_cross_check_reason
                        FROM auto_buy_decision_snapshots ads
                        WHERE ads.symbol = abc.symbol
                          AND ads.candidate_timestamp = abc.timestamp
                        ORDER BY ads.id DESC
                        LIMIT 1
                    )
                """
                prediction_score_expr = """
                    (
                        SELECT json_extract(ads.candidate_json, '$.ml_prediction_score')
                        FROM auto_buy_decision_snapshots ads
                        WHERE ads.symbol = abc.symbol
                          AND ads.candidate_timestamp = abc.timestamp
                        ORDER BY ads.id DESC
                        LIMIT 1
                    )
                    """
                prediction_decision_expr = """
                    (
                        SELECT json_extract(ads.candidate_json, '$.ml_prediction_decision')
                        FROM auto_buy_decision_snapshots ads
                        WHERE ads.symbol = abc.symbol
                          AND ads.candidate_timestamp = abc.timestamp
                        ORDER BY ads.id DESC
                        LIMIT 1
                    )
                    """
            if _table_exists(con, "auto_buy_intraday_feedback"):
                live_feedback_status_expr = """
                    (
                        SELECT fb.status
                        FROM auto_buy_intraday_feedback fb
                        WHERE fb.symbol = abc.symbol
                          AND substr(fb.created_at, 1, 10) = substr(abc.timestamp, 1, 10)
                        ORDER BY fb.id DESC
                        LIMIT 1
                    )
                """
                live_feedback_penalty_expr = """
                    (
                        SELECT fb.score_penalty
                        FROM auto_buy_intraday_feedback fb
                        WHERE fb.symbol = abc.symbol
                          AND substr(fb.created_at, 1, 10) = substr(abc.timestamp, 1, 10)
                        ORDER BY fb.id DESC
                        LIMIT 1
                    )
                """

            auto_rows = con.execute(
                f"""
                SELECT
                    -abc.id AS id,
                    abc.timestamp,
                    abc.symbol,
                    'buy' AS action,
                    NULL AS signal_price,
                    CASE WHEN abc.order_submitted = 1 THEN 1 ELSE 0 END AS approved,
                    COALESCE(
                        NULLIF({live_block_expr}, ''),
                        NULLIF(abc.hard_block_reason, ''),
                        CASE
                            WHEN abc.order_submitted = 0
                              THEN 'auto_buy_candidate:' || COALESCE(abc.decision, 'reviewed')
                            ELSE NULL
                        END
                    ) AS rejection_reason,

                    abc.market_bias,
                    abc.market_bias AS market_bias_effective,
                    NULL AS fundamental_score,
                    abc.risk_level,
                    abc.entry_quality,
                    NULL AS trend_direction,
                    NULL AS trend_strength,
                    CASE
                        WHEN abc.momentum_5m_pct > 0 THEN 'rising'
                        WHEN abc.momentum_5m_pct < 0 THEN 'falling'
                        ELSE NULL
                    END AS momentum_direction,
                    abc.momentum_5m_pct AS momentum_pct,

                    abc.session_trend_label,
                    abc.session_trend_score,
                    abc.session_return_pct,
                    abc.momentum_5m_pct AS session_momentum_5m_pct,
                    abc.momentum_15m_pct AS session_momentum_15m_pct,
                    abc.momentum_30m_pct AS session_momentum_30m_pct,
                    abc.distance_from_vwap_pct AS session_distance_from_vwap_pct,

                    {prediction_score_expr} AS prediction_score,
                    {prediction_decision_expr} AS prediction_decision,

                    abc.setup_label,
                    abc.setup_recommendation AS setup_policy_action,
                    abc.setup_score AS setup_size_multiplier,

                    abc.score AS buy_opportunity_score,
                    abc.decision AS buy_opportunity_recommendation,
                    COALESCE({risk_cross_check_expr}, abc.reason) AS buy_opportunity_reason,
                    {live_feedback_status_expr} AS live_feedback_status,
                    {live_feedback_penalty_expr} AS live_feedback_penalty
                FROM auto_buy_candidates abc
                WHERE abc.timestamp >= ?
                  AND abc.decision IN ('strong_buy_candidate', 'buy_candidate', 'watch')
                ORDER BY abc.timestamp DESC, abc.id DESC
                LIMIT ?
                """,
                (since_timestamp, limit),
            ).fetchall()

        rows = list(trade_rows) + list(auto_rows)
        rows.sort(key=lambda r: (str(r["timestamp"] or ""), int(r["id"] or 0)), reverse=True)
        return rows[:limit]


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
