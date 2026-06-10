from __future__ import annotations

import sqlite3


class OpsCheckConvictionQueriesMixin:
    def conviction_stack_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                effective_size_cap_pct,
                dominant_limiter,
                buy_opportunity_recommendation,
                setup_policy_action,
                session_momentum_severity,
                trader_brain_score,
                ml_prediction_bucket,
                approved
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
            ORDER BY timestamp
            """,
            (target_date,),
        )

    def conviction_persistence_health(self, target_date: str) -> sqlite3.Row | None:
        return self._fetchone(
            """
            SELECT
                COUNT(*) AS buy_rows,
                SUM(CASE WHEN dominant_limiter IS NOT NULL
                          AND dominant_limiter != ''
                         THEN 1 ELSE 0 END) AS dominant_limiter_populated,
                SUM(CASE WHEN dominant_limiter IS NOT NULL
                          AND dominant_limiter != ''
                          AND dominant_limiter != 'unknown'
                         THEN 1 ELSE 0 END) AS dominant_limiter_meaningful,
                SUM(CASE WHEN effective_size_cap_pct IS NOT NULL
                         THEN 1 ELSE 0 END) AS effective_size_cap_populated,
                SUM(CASE WHEN effective_size_cap_pct IS NOT NULL
                         THEN 1 ELSE 0 END) AS was_capped,
                SUM(CASE WHEN buy_opportunity_score IS NOT NULL
                         THEN 1 ELSE 0 END) AS buy_opportunity_score_populated,
                SUM(CASE WHEN buy_opportunity_recommendation IS NOT NULL
                          AND buy_opportunity_recommendation != ''
                         THEN 1 ELSE 0 END) AS buy_opportunity_bucket_populated,
                SUM(CASE WHEN trader_brain_score IS NOT NULL
                         THEN 1 ELSE 0 END) AS strategy_score_populated,
                SUM(CASE WHEN session_trend_label IS NOT NULL
                          AND session_trend_label != ''
                         THEN 1 ELSE 0 END) AS session_momentum_label_populated,
                SUM(CASE WHEN ml_prediction_bucket IS NOT NULL
                          AND ml_prediction_bucket != ''
                         THEN 1 ELSE 0 END) AS ml_prediction_bucket_populated,
                SUM(CASE WHEN setup_policy_action IS NOT NULL
                          AND setup_policy_action != ''
                         THEN 1 ELSE 0 END) AS setup_policy_action_populated,
                SUM(CASE WHEN (
                            dominant_limiter IS NOT NULL
                            AND dominant_limiter != ''
                         )
                          AND buy_opportunity_score IS NOT NULL
                          AND (
                            buy_opportunity_recommendation IS NOT NULL
                            AND buy_opportunity_recommendation != ''
                          )
                          AND (
                            trader_brain_score IS NOT NULL
                            OR confidence = 'auto_buy_manager'
                          )
                          AND (
                            session_trend_label IS NOT NULL
                            AND session_trend_label != ''
                          )
                          AND (
                            ml_prediction_bucket IS NOT NULL
                            AND ml_prediction_bucket != ''
                          )
                          AND (
                            setup_policy_action IS NOT NULL
                            AND setup_policy_action != ''
                          )
                         THEN 1 ELSE 0 END) AS conviction_stack_composite_present
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
            """,
            (target_date,),
        )

    def conviction_persistence_stage_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            WITH staged AS (
                SELECT
                    *,
                    CASE
                        WHEN approved = 1 THEN 'approved'
                        WHEN rejection_reason LIKE 'second_look:%'
                          OR rejection_reason LIKE 'one_bar_confirmation:%'
                          OR rejection_reason LIKE 'order_path_exception:%'
                          OR rejection_reason LIKE 'broker_submit:%'
                          OR rejection_reason LIKE 'submit_failed:%'
                        THEN 'execution_rejection'
                        WHEN buy_opportunity_score IS NOT NULL
                          OR trader_brain_score IS NOT NULL
                          OR dominant_limiter IS NOT NULL
                          OR effective_size_cap_pct IS NOT NULL
                        THEN 'post_context_rejection'
                        ELSE 'pre_context_rejection'
                    END AS inferred_stage,
                    CASE WHEN (
                            dominant_limiter IS NOT NULL
                            AND dominant_limiter != ''
                         )
                          AND buy_opportunity_score IS NOT NULL
                          AND (
                            buy_opportunity_recommendation IS NOT NULL
                            AND buy_opportunity_recommendation != ''
                          )
                          AND (
                            trader_brain_score IS NOT NULL
                            OR confidence = 'auto_buy_manager'
                          )
                          AND (
                            session_trend_label IS NOT NULL
                            AND session_trend_label != ''
                          )
                          AND (
                            ml_prediction_bucket IS NOT NULL
                            AND ml_prediction_bucket != ''
                          )
                          AND (
                            setup_policy_action IS NOT NULL
                            AND setup_policy_action != ''
                          )
                         THEN 1 ELSE 0 END AS has_complete_conviction_stack
                FROM trades
                WHERE date(timestamp) = ?
                  AND action = 'buy'
            )
            SELECT
                inferred_stage,
                COUNT(*) AS rows,
                SUM(CASE WHEN has_complete_conviction_stack = 1 THEN 1 ELSE 0 END)
                    AS complete_conviction_stack,
                SUM(CASE WHEN dominant_limiter IS NOT NULL
                          AND dominant_limiter != ''
                         THEN 1 ELSE 0 END) AS dominant_limiter_populated,
                SUM(CASE WHEN dominant_limiter IS NOT NULL
                          AND dominant_limiter != ''
                          AND dominant_limiter != 'unknown'
                         THEN 1 ELSE 0 END) AS dominant_limiter_meaningful,
                SUM(CASE WHEN effective_size_cap_pct IS NOT NULL
                         THEN 1 ELSE 0 END) AS cap_fields_populated,
                SUM(CASE WHEN buy_opportunity_score IS NOT NULL
                         THEN 1 ELSE 0 END) AS buy_opportunity_score_populated,
                SUM(CASE WHEN ml_prediction_bucket IS NOT NULL
                          AND ml_prediction_bucket != ''
                         THEN 1 ELSE 0 END) AS ml_prediction_bucket_populated,
                SUM(CASE WHEN setup_policy_action IS NOT NULL
                          AND setup_policy_action != ''
                         THEN 1 ELSE 0 END) AS setup_policy_action_populated
            FROM staged
            GROUP BY inferred_stage
            ORDER BY
                CASE inferred_stage
                    WHEN 'pre_context_rejection' THEN 1
                    WHEN 'post_context_rejection' THEN 2
                    WHEN 'execution_rejection' THEN 3
                    WHEN 'approved' THEN 4
                    ELSE 5
                END
            """,
            (target_date,),
        )

    def conviction_persistence_sample_rows(
        self,
        target_date: str,
        limit: int,
    ) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                id,
                timestamp,
                symbol,
                approved,
                CASE
                    WHEN approved = 1 THEN 'approved'
                    WHEN rejection_reason IS NULL OR rejection_reason = '' THEN 'none'
                    WHEN instr(rejection_reason, ':') > 0
                        THEN substr(rejection_reason, 1, instr(rejection_reason, ':') - 1)
                    ELSE substr(rejection_reason, 1, 32)
                END AS rejection_category,
                setup_policy_action,
                ml_prediction_bucket,
                buy_opportunity_recommendation,
                trader_brain_score,
                session_trend_label,
                effective_size_cap_pct,
                dominant_limiter
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
            ORDER BY id DESC
            LIMIT ?
            """,
            (target_date, limit),
        )

    def buy_opportunity_signal_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                buy_opportunity_recommendation AS rec,
                COUNT(*) AS signals,
                SUM(approved) AS approved,
                AVG(CAST(approved AS REAL)) * 100 AS appr_pct,
                MIN(buy_opportunity_score) AS min_score,
                MAX(buy_opportunity_score) AS max_score,
                AVG(buy_opportunity_score) AS avg_score
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
              AND buy_opportunity_recommendation IS NOT NULL
            GROUP BY buy_opportunity_recommendation
            ORDER BY AVG(buy_opportunity_score) DESC
            """,
            (target_date,),
        )

    def buy_opportunity_pnl_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                t.buy_opportunity_recommendation AS rec,
                COUNT(mt.id) AS exits,
                AVG(mt.realized_pnl_pct) AS avg_pnl,
                SUM(CASE WHEN mt.realized_pnl_pct > 0 THEN 1 ELSE 0 END) AS wins,
                AVG(mt.capture_ratio) AS avg_capture
            FROM trades t
            JOIN matched_trades mt
              ON mt.symbol = t.symbol
             AND ABS(julianday(mt.entry_timestamp) - julianday(t.timestamp)) < 0.01
            WHERE date(t.timestamp) = ?
              AND t.action = 'buy'
              AND t.approved = 1
              AND t.buy_opportunity_recommendation IS NOT NULL
            GROUP BY t.buy_opportunity_recommendation
            ORDER BY AVG(mt.realized_pnl_pct) DESC
            """,
            (target_date,),
        )

    def buy_opportunity_cap_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                buy_opportunity_recommendation AS rec,
                dominant_limiter,
                COUNT(*) AS n
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
              AND buy_opportunity_recommendation IS NOT NULL
            GROUP BY buy_opportunity_recommendation, dominant_limiter
            ORDER BY rec, n DESC
            """,
            (target_date,),
        )

    def buy_opportunity_double_count_row(self, target_date: str) -> sqlite3.Row | None:
        return self._fetchone(
            """
            SELECT COUNT(*) AS n
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
              AND setup_policy_action IN ('block', 'error')
              AND buy_opportunity_recommendation = 'avoid'
            """,
            (target_date,),
        )

    def claude_daily_approval_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                date(timestamp) AS day,
                COUNT(*) AS total,
                SUM(approved) AS approved,
                AVG(CAST(approved AS REAL)) * 100 AS appr_pct
            FROM trades
            WHERE action = 'buy'
              AND date(timestamp) >= date(?, '-14 days')
            GROUP BY date(timestamp)
            ORDER BY date(timestamp)
            """,
            (target_date,),
        )

    def claude_rejection_reason_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                rejection_reason,
                COUNT(*) AS n
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
              AND approved = 0
              AND rejection_reason IS NOT NULL
            ORDER BY n DESC
            LIMIT 12
            """,
            (target_date,),
        )

    def claude_confidence_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                confidence,
                COUNT(*) AS n,
                ROUND(COUNT(*) * 100.0 / SUM(COUNT(*)) OVER (), 1) AS pct
            FROM trades
            WHERE action = 'buy'
              AND approved = 1
              AND confidence IS NOT NULL
              AND date(timestamp) >= date(?, '-30 days')
            GROUP BY confidence
            ORDER BY n DESC
            """,
            (target_date,),
        )
