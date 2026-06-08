from __future__ import annotations

import sqlite3
from typing import Any


class OpsCheckExcursionQueriesMixin:
    def capture_by_exit_type_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                CASE
                    WHEN exit_reason LIKE 'position_manager_full%'    THEN 'pm_full_exit'
                    WHEN exit_reason LIKE 'position_manager_partial%'  THEN 'pm_partial_exit'
                    WHEN exit_reason LIKE 'synthetic_bracket%'         THEN 'bracket_exit'
                    ELSE COALESCE(SUBSTR(exit_reason, 1, 22), 'unknown')
                END AS exit_type,
                COUNT(*) AS n,
                SUM(CASE WHEN mfe_pct IS NOT NULL THEN 1 ELSE 0 END) AS has_mfe,
                ROUND(AVG(mfe_pct), 3) AS avg_mfe,
                ROUND(AVG(realized_pnl_pct), 3) AS avg_pnl,
                ROUND(AVG(capture_ratio), 3) AS avg_capture,
                SUM(CASE WHEN mfe_pct >= 0.40 AND realized_pnl_pct <= 0 THEN 1 ELSE 0 END)
                    AS winners_became_losers
            FROM matched_trades
            WHERE exit_timestamp IS NOT NULL
              AND DATE(exit_timestamp) = ?
            GROUP BY exit_type
            ORDER BY n DESC
            """,
            (target_date,),
        )

    def peak_bucket_rows(self, target_date: str | None = None) -> list[sqlite3.Row]:
        where_clause = "WHERE mfe_pct IS NOT NULL"
        params: tuple[Any, ...] = ()
        if target_date:
            where_clause += " AND DATE(exit_timestamp) = ?"
            params = (target_date,)
        return self._fetchall(
            f"""
            WITH base AS (
                SELECT
                    *,
                    CASE
                        WHEN LOWER(COALESCE(setup_policy_action, '')) = 'error'
                          OR LOWER(COALESCE(prediction_decision, '')) IN ('watch', 'caution')
                          OR LOWER(COALESCE(buy_opportunity_recommendation, '')) IN ('small_buy_candidate', 'watch')
                          OR LOWER(COALESCE(ml_prediction_bucket, '')) = 'weak_below_45'
                          OR LOWER(COALESCE(setup_label, '')) LIKE '%fade_risk%'
                          OR LOWER(COALESCE(setup_label, '')) LIKE '%neutral_fade%'
                          OR LOWER(COALESCE(setup_label, '')) LIKE '%drift_risk%'
                          OR LOWER(COALESCE(setup_label, '')) LIKE '%unclassified%'
                        THEN 1 ELSE 0
                    END AS weak_entry_context
                FROM matched_trades
                {where_clause}
            ),
            enriched AS (
                SELECT
                    *,
                    CASE
                        WHEN weak_entry_context = 1 AND mfe_pct >= 0.50 THEN 0.25
                        WHEN weak_entry_context = 1 AND mfe_pct >= 0.30 THEN 0.10
                        WHEN weak_entry_context = 0 AND mfe_pct >= 1.00 THEN 0.30
                        WHEN weak_entry_context = 0 AND mfe_pct >= 0.60 THEN 0.20
                        WHEN weak_entry_context = 0 AND mfe_pct >= 0.30 THEN 0.10
                        ELSE NULL
                    END AS peak_lock_floor_pct
                FROM base
            )
            SELECT
                CASE
                    WHEN mfe_pct >= 1.00 THEN '1.00%+'
                    WHEN mfe_pct >= 0.60 THEN '0.60-1.00%'
                    WHEN mfe_pct >= 0.30 THEN '0.30-0.60%'
                    ELSE '<0.30%'
                END AS peak_bucket,
                COUNT(*) AS trades,
                ROUND(AVG(realized_pnl_pct), 3) AS avg_pnl,
                ROUND(100.0 * SUM(won) / COUNT(*), 1) AS win_rate,
                ROUND(AVG(mfe_pct), 3) AS avg_mfe,
                ROUND(AVG(capture_ratio), 3) AS avg_capture,
                SUM(CASE WHEN realized_pnl_pct < 0 THEN 1 ELSE 0 END) AS exits_below_zero,
                SUM(CASE WHEN mfe_pct >= 0.30 AND realized_pnl_pct <= 0
                         THEN 1 ELSE 0 END) AS winner_became_loser,
                SUM(weak_entry_context) AS weak_entries,
                ROUND(AVG(peak_lock_floor_pct), 3) AS avg_peak_lock_floor,
                SUM(CASE WHEN peak_lock_floor_pct IS NOT NULL
                          AND realized_pnl_pct <= peak_lock_floor_pct
                         THEN 1 ELSE 0 END) AS floor_triggered,
                SUM(CASE WHEN mfe_pct >= 0.40
                          AND realized_pnl_pct <= 0
                          AND peak_lock_floor_pct IS NOT NULL
                         THEN 1 ELSE 0 END) AS would_have_been_winner_became_loser
            FROM enriched
            GROUP BY peak_bucket
            ORDER BY
                CASE peak_bucket
                    WHEN '1.00%+'     THEN 1
                    WHEN '0.60-1.00%' THEN 2
                    WHEN '0.30-0.60%' THEN 3
                    ELSE 4
                END
            """,
            params,
        )

    def peak_bucket_total(self, target_date: str | None = None) -> sqlite3.Row | None:
        where_clause = "WHERE 1=1"
        params: tuple[Any, ...] = ()
        if target_date:
            where_clause += " AND DATE(exit_timestamp) = ?"
            params = (target_date,)
        return self._fetchone(
            f"""
            SELECT COUNT(*) AS n, SUM(CASE WHEN mfe_pct IS NOT NULL THEN 1 ELSE 0 END) AS with_mfe
            FROM matched_trades
            {where_clause}
            """,
            params,
        )

    def winner_became_loser_summary(
        self, target_date: str, mfe_threshold: float
    ) -> sqlite3.Row | None:
        return self._fetchone(
            """
            SELECT
                COUNT(*) AS total,
                SUM(CASE WHEN mfe_pct IS NOT NULL THEN 1 ELSE 0 END) AS has_mfe,
                SUM(CASE WHEN mfe_pct >= ? AND realized_pnl_pct <= 0 THEN 1 ELSE 0 END)
                    AS true_wbl,
                SUM(CASE WHEN mfe_pct >= ? AND realized_pnl_pct > 0
                          AND (capture_ratio IS NULL OR capture_ratio < 0.50)
                          THEN 1 ELSE 0 END) AS poor_capture
            FROM matched_trades
            WHERE DATE(exit_timestamp) = ?
            """,
            (mfe_threshold, mfe_threshold, target_date),
        )

    def winner_became_loser_rows(self, target_date: str, mfe_threshold: float) -> list[sqlite3.Row]:
        has_exit_snapshots = self.table_exists("exit_snapshots")
        exit_cols = self.table_columns("exit_snapshots") if has_exit_snapshots else set()
        join_sql = (
            "LEFT JOIN exit_snapshots es ON es.matched_trade_id = enriched.id"
            if has_exit_snapshots and "matched_trade_id" in exit_cols
            else ""
        )
        exit_fields = (
            """
                es.id AS exit_snapshot_id,
                es.exit_trigger AS exit_snapshot_trigger,
                es.avoided_drawdown_pct,
                es.missed_upside_pct,
                es.post_exit_return_30m_pct,
                es.post_exit_return_60m_pct,
                es.reentry_window_summary,
            """
            if join_sql
            else """
                NULL AS exit_snapshot_id,
                NULL AS exit_snapshot_trigger,
                NULL AS avoided_drawdown_pct,
                NULL AS missed_upside_pct,
                NULL AS post_exit_return_30m_pct,
                NULL AS post_exit_return_60m_pct,
                NULL AS reentry_window_summary,
            """
        )
        return self._fetchall(
            f"""
            WITH base AS (
                SELECT
                    *,
                    CASE
                        WHEN LOWER(COALESCE(setup_policy_action, '')) = 'error'
                          OR LOWER(COALESCE(prediction_decision, '')) IN ('watch', 'caution')
                          OR LOWER(COALESCE(buy_opportunity_recommendation, '')) IN ('small_buy_candidate', 'watch')
                          OR LOWER(COALESCE(ml_prediction_bucket, '')) = 'weak_below_45'
                          OR LOWER(COALESCE(setup_label, '')) LIKE '%fade_risk%'
                          OR LOWER(COALESCE(setup_label, '')) LIKE '%neutral_fade%'
                          OR LOWER(COALESCE(setup_label, '')) LIKE '%drift_risk%'
                          OR LOWER(COALESCE(setup_label, '')) LIKE '%unclassified%'
                        THEN 1 ELSE 0
                    END AS weak_entry_context
                FROM matched_trades
            ),
            enriched AS (
                SELECT
                    *,
                    CASE
                        WHEN weak_entry_context = 1 AND mfe_pct >= 0.50 THEN 0.25
                        WHEN weak_entry_context = 1 AND mfe_pct >= 0.30 THEN 0.10
                        WHEN weak_entry_context = 0 AND mfe_pct >= 1.00 THEN 0.30
                        WHEN weak_entry_context = 0 AND mfe_pct >= 0.60 THEN 0.20
                        WHEN weak_entry_context = 0 AND mfe_pct >= 0.30 THEN 0.10
                        ELSE NULL
                    END AS peak_lock_floor_pct,
                    CASE
                        WHEN weak_entry_context = 1 AND mfe_pct >= 0.50 THEN 'weak_tier2'
                        WHEN weak_entry_context = 1 AND mfe_pct >= 0.30 THEN 'weak_tier1'
                        WHEN weak_entry_context = 0 AND mfe_pct >= 1.00 THEN 'strong_tier3'
                        WHEN weak_entry_context = 0 AND mfe_pct >= 0.60 THEN 'strong_tier2'
                        WHEN weak_entry_context = 0 AND mfe_pct >= 0.30 THEN 'strong_tier1'
                        ELSE NULL
                    END AS peak_lock_tier
                FROM base
            )
            SELECT
                {exit_fields}
                enriched.symbol, enriched.entry_timestamp, enriched.exit_timestamp,
                enriched.holding_minutes, enriched.realized_pnl_pct, enriched.mfe_pct, enriched.capture_ratio,
                enriched.setup_policy_action, enriched.exit_reason,
                weak_entry_context, peak_lock_floor_pct, peak_lock_tier,
                CASE WHEN peak_lock_floor_pct IS NOT NULL
                       AND enriched.realized_pnl_pct <= peak_lock_floor_pct
                     THEN 1 ELSE 0 END AS floor_triggered,
                CASE WHEN enriched.mfe_pct >= ?
                       AND enriched.realized_pnl_pct <= 0
                       AND peak_lock_floor_pct IS NOT NULL
                     THEN 1 ELSE 0 END AS would_have_been_winner_became_loser
            FROM enriched
            {join_sql}
            WHERE DATE(enriched.exit_timestamp) = ?
              AND enriched.mfe_pct >= ?
              AND enriched.realized_pnl_pct <= 0
            ORDER BY enriched.realized_pnl_pct ASC
            """,
            (mfe_threshold, target_date, mfe_threshold),
        )

    def poor_capture_rows(self, target_date: str, mfe_threshold: float) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                symbol, holding_minutes, realized_pnl_pct, mfe_pct, capture_ratio,
                setup_policy_action, exit_reason
            FROM matched_trades
            WHERE DATE(exit_timestamp) = ?
              AND mfe_pct >= ?
              AND realized_pnl_pct > 0
              AND (capture_ratio IS NULL OR capture_ratio < 0.50)
            ORDER BY capture_ratio ASC NULLS LAST
            """,
            (target_date, mfe_threshold),
        )

    def all_mfe_rows_for_date(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            WITH base AS (
                SELECT
                    *,
                    CASE
                        WHEN LOWER(COALESCE(setup_policy_action, '')) = 'error'
                          OR LOWER(COALESCE(prediction_decision, '')) IN ('watch', 'caution')
                          OR LOWER(COALESCE(buy_opportunity_recommendation, '')) IN ('small_buy_candidate', 'watch')
                          OR LOWER(COALESCE(ml_prediction_bucket, '')) = 'weak_below_45'
                          OR LOWER(COALESCE(setup_label, '')) LIKE '%fade_risk%'
                          OR LOWER(COALESCE(setup_label, '')) LIKE '%neutral_fade%'
                          OR LOWER(COALESCE(setup_label, '')) LIKE '%drift_risk%'
                          OR LOWER(COALESCE(setup_label, '')) LIKE '%unclassified%'
                        THEN 1 ELSE 0
                    END AS weak_entry_context
                FROM matched_trades
            )
            SELECT
                symbol, realized_pnl_pct, mfe_pct, capture_ratio,
                setup_policy_action, weak_entry_context,
                CASE
                    WHEN weak_entry_context = 1 AND mfe_pct >= 0.50 THEN 0.25
                    WHEN weak_entry_context = 1 AND mfe_pct >= 0.30 THEN 0.10
                    WHEN weak_entry_context = 0 AND mfe_pct >= 1.00 THEN 0.30
                    WHEN weak_entry_context = 0 AND mfe_pct >= 0.60 THEN 0.20
                    WHEN weak_entry_context = 0 AND mfe_pct >= 0.30 THEN 0.10
                    ELSE NULL
                END AS peak_lock_floor_pct
            FROM base
            WHERE DATE(exit_timestamp) = ?
              AND mfe_pct IS NOT NULL
            ORDER BY capture_ratio ASC NULLS FIRST
            """,
            (target_date,),
        )
