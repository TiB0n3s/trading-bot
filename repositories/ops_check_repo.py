from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


class OpsCheckRepository:
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def exists(self) -> bool:
        return self.db_path.exists()

    def table_exists(self, table_name: str) -> bool:
        row = self._fetchone(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        )
        return row is not None

    def table_columns(self, table_name: str) -> set[str]:
        rows = self._fetchall(f"PRAGMA table_info({table_name})")
        return {row["name"] for row in rows}

    def table_count(
        self,
        table_name: str,
        where_sql: str = "",
        params: tuple[Any, ...] = (),
    ) -> int | None:
        if not self.table_exists(table_name):
            return None

        sql = f"SELECT COUNT(*) AS n FROM {table_name}"
        if where_sql:
            sql += f" WHERE {where_sql}"
        row = self._fetchone(sql, params)
        return int(row["n"] or 0) if row else 0

    def _fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            return con.execute(sql, params).fetchall()

    def _fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            return con.execute(sql, params).fetchone()

    def setup_overview_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                COALESCE(setup_policy_action, 'NULL') AS action,
                COUNT(*) AS signals,
                SUM(approved) AS approved,
                SUM(CASE WHEN approved = 0 THEN 1 ELSE 0 END) AS rejected
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
            GROUP BY setup_policy_action
            ORDER BY signals DESC
            """,
            (target_date,),
        )

    def setup_error_symbol_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                symbol,
                COUNT(*) AS signals,
                SUM(approved) AS approved,
                COALESCE(setup_unknown_reason, setup_policy_reason, 'no_reason') AS reason
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
              AND (
                  setup_policy_action = 'error'
                  OR setup_unknown_reason IS NOT NULL
              )
            GROUP BY symbol, setup_unknown_reason, setup_policy_reason
            ORDER BY signals DESC
            LIMIT 20
            """,
            (target_date,),
        )

    def setup_error_hour_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                CAST(strftime('%H', timestamp) AS INTEGER) AS hour_et,
                COUNT(*) AS signals,
                SUM(approved) AS approved
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
              AND (
                  setup_policy_action = 'error'
                  OR setup_unknown_reason IS NOT NULL
              )
            GROUP BY hour_et
            ORDER BY hour_et
            """,
            (target_date,),
        )

    def setup_feed_error_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                CASE
                    WHEN setup_unknown_reason LIKE '%subscription%'
                      OR setup_policy_reason LIKE '%subscription%'
                        THEN 'sip_subscription_failure'
                    WHEN setup_policy_action = 'error' THEN 'other_snapshot_error'
                    WHEN setup_unknown_reason IS NOT NULL THEN 'label_unknown'
                    ELSE 'no_error'
                END AS error_category,
                COUNT(*) AS signals,
                SUM(approved) AS approved
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
            GROUP BY error_category
            ORDER BY signals DESC
            """,
            (target_date,),
        )

    def setup_pnl_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                COALESCE(setup_policy_action, 'NULL') AS spa,
                COUNT(*) AS trades,
                SUM(won) AS wins,
                ROUND(AVG(realized_pnl_pct), 3) AS avg_pnl_pct,
                ROUND(SUM(realized_pnl_pct), 2) AS total_pnl_pct
            FROM matched_trades
            WHERE date(entry_timestamp) = ?
            GROUP BY setup_policy_action
            ORDER BY trades DESC
            """,
            (target_date,),
        )

    def approved_unknown_setup_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                mt.symbol,
                mt.setup_policy_action,
                COALESCE(mt.setup_unknown_reason, mt.setup_policy_reason, '') AS unknown_reason,
                ROUND(mt.realized_pnl_pct, 3) AS pnl_pct,
                mt.won,
                mt.holding_minutes
            FROM matched_trades mt
            WHERE date(mt.entry_timestamp) = ?
              AND (
                  mt.setup_policy_action = 'error'
                  OR mt.setup_unknown_reason IS NOT NULL
              )
            ORDER BY mt.entry_timestamp
            """,
            (target_date,),
        )

    def prediction_bucket_signal_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                COALESCE(ml_prediction_bucket, 'unknown') AS bucket,
                COUNT(*) AS signals,
                SUM(approved) AS approved,
                ROUND(100.0 * SUM(approved) / COUNT(*), 1) AS approval_rate_pct
            FROM trades
            WHERE date(timestamp) = ?
              AND action = 'buy'
            GROUP BY bucket
            ORDER BY
                CASE bucket
                    WHEN 'high_55_plus'  THEN 1
                    WHEN 'mid_50_55'     THEN 2
                    WHEN 'low_45_50'     THEN 3
                    WHEN 'weak_below_45' THEN 4
                    ELSE 5
                END
            """,
            (target_date,),
        )

    def prediction_bucket_pnl_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                COALESCE(mt.ml_prediction_bucket, 'unknown') AS bucket,
                COUNT(*) AS trades,
                SUM(mt.won) AS wins,
                ROUND(AVG(mt.realized_pnl_pct), 3) AS avg_pnl_pct,
                ROUND(SUM(mt.realized_pnl_pct), 2) AS total_pnl_pct
            FROM matched_trades mt
            WHERE date(mt.entry_timestamp) = ?
            GROUP BY bucket
            ORDER BY
                CASE bucket
                    WHEN 'high_55_plus'  THEN 1
                    WHEN 'mid_50_55'     THEN 2
                    WHEN 'low_45_50'     THEN 3
                    WHEN 'weak_below_45' THEN 4
                    ELSE 5
                END
            """,
            (target_date,),
        )

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
                         THEN 1 ELSE 0 END) AS winner_became_loser
            FROM matched_trades
            {where_clause}
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

    def winner_became_loser_summary(self, target_date: str, mfe_threshold: float) -> sqlite3.Row | None:
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
        return self._fetchall(
            """
            SELECT
                symbol, entry_timestamp, exit_timestamp,
                holding_minutes, realized_pnl_pct, mfe_pct, capture_ratio,
                setup_policy_action, exit_reason
            FROM matched_trades
            WHERE DATE(exit_timestamp) = ?
              AND mfe_pct >= ?
              AND realized_pnl_pct <= 0
            ORDER BY realized_pnl_pct ASC
            """,
            (target_date, mfe_threshold),
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
            SELECT
                symbol, realized_pnl_pct, mfe_pct, capture_ratio,
                setup_policy_action
            FROM matched_trades
            WHERE DATE(exit_timestamp) = ?
              AND mfe_pct IS NOT NULL
            ORDER BY capture_ratio ASC NULLS FIRST
            """,
            (target_date,),
        )

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

    def rejection_total_count(self, target_date: str) -> int:
        row = self._fetchone(
            """
            SELECT COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
            """,
            (target_date,),
        )
        return int(row["n"] or 0) if row else 0

    def rejection_approved_count(self, target_date: str) -> int:
        row = self._fetchone(
            """
            SELECT COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND approved = 1
            """,
            (target_date,),
        )
        return int(row["n"] or 0) if row else 0

    def rejection_rejected_count(self, target_date: str) -> int:
        row = self._fetchone(
            """
            SELECT COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND COALESCE(approved, 0) = 0
            """,
            (target_date,),
        )
        return int(row["n"] or 0) if row else 0

    def rejection_action_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT COALESCE(action, 'missing') AS action,
                   COALESCE(approved, 0) AS approved,
                   COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
            GROUP BY COALESCE(action, 'missing'), COALESCE(approved, 0)
            ORDER BY action, approved DESC
            """,
            (target_date,),
        )

    def rejection_reason_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT rejection_reason, COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND COALESCE(approved, 0) = 0
            GROUP BY rejection_reason
            ORDER BY n DESC, rejection_reason
            """,
            (target_date,),
        )

    def rejected_symbol_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT COALESCE(symbol, 'missing') AS symbol, COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND COALESCE(approved, 0) = 0
            GROUP BY COALESCE(symbol, 'missing')
            ORDER BY n DESC, symbol
            LIMIT 15
            """,
            (target_date,),
        )

    def recent_rejected_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT timestamp, symbol, action, rejection_reason, confidence,
                   prediction_score, prediction_decision, setup_label,
                   buy_opportunity_score, buy_opportunity_recommendation
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND COALESCE(approved, 0) = 0
            ORDER BY timestamp DESC, id DESC
            LIMIT 12
            """,
            (target_date,),
        )

    def rejected_outcome_rejected_counts(self, target_date: str) -> sqlite3.Row | None:
        return self._fetchone(
            """
            SELECT
                COUNT(*) AS n,
                SUM(CASE WHEN LOWER(action) = 'buy' THEN 1 ELSE 0 END) AS buy_n,
                SUM(CASE WHEN LOWER(action) = 'sell' THEN 1 ELSE 0 END) AS sell_n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND approved = 0
              AND symbol IS NOT NULL
              AND action IS NOT NULL
              AND signal_price IS NOT NULL
              AND LOWER(action) IN ('buy', 'sell')
            """,
            (target_date,),
        )

    def rejected_outcome_status_counts(self, target_date: str) -> sqlite3.Row | None:
        return self._fetchone(
            """
            SELECT
                COUNT(*) AS n,
                SUM(CASE WHEN label_status = 'labeled' THEN 1 ELSE 0 END) AS labeled,
                SUM(CASE WHEN label_status = 'partial' THEN 1 ELSE 0 END) AS partial,
                SUM(CASE WHEN label_status = 'pending' THEN 1 ELSE 0 END) AS pending,
                SUM(CASE WHEN label_status = 'no_bars' THEN 1 ELSE 0 END) AS no_bars,
                SUM(CASE WHEN label_status = 'error' THEN 1 ELSE 0 END) AS error
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
            """,
            (target_date,),
        )

    def rejected_outcome_partial_reason_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT COALESCE(partial_reason, 'unspecified') AS partial_reason,
                   COUNT(*) AS n
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
              AND label_status IN ('partial', 'pending', 'no_bars')
            GROUP BY COALESCE(partial_reason, 'unspecified')
            ORDER BY n DESC, partial_reason
            """,
            (target_date,),
        )

    def rejected_outcome_horizon_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                label_status,
                COUNT(*) AS n,
                SUM(CASE WHEN return_5m IS NOT NULL THEN 1 ELSE 0 END) AS has_5m,
                SUM(CASE WHEN return_15m IS NOT NULL THEN 1 ELSE 0 END) AS has_15m,
                SUM(CASE WHEN return_30m IS NOT NULL THEN 1 ELSE 0 END) AS has_30m,
                SUM(CASE WHEN return_60m IS NOT NULL THEN 1 ELSE 0 END) AS has_60m,
                SUM(CASE WHEN return_eod IS NOT NULL THEN 1 ELSE 0 END) AS has_eod,
                SUM(CASE WHEN max_favorable_60m IS NOT NULL THEN 1 ELSE 0 END) AS has_mfe,
                SUM(CASE WHEN max_adverse_60m IS NOT NULL THEN 1 ELSE 0 END) AS has_mae
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
            GROUP BY label_status
            ORDER BY label_status
            """,
            (target_date,),
        )

    def rejected_outcome_action_status_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT action, label_status, COUNT(*) AS n,
                   AVG(return_15m) AS avg_return_15m,
                   AVG(return_60m) AS avg_return_60m,
                   AVG(return_eod) AS avg_return_eod
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
            GROUP BY action, label_status
            ORDER BY action, label_status
            """,
            (target_date,),
        )

    def rejected_outcome_invalid_labeled_count(self, target_date: str) -> int:
        row = self._fetchone(
            """
            SELECT COUNT(*) AS n
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
              AND label_status = 'labeled'
              AND (
                   return_5m IS NULL
                OR return_15m IS NULL
                OR return_30m IS NULL
                OR return_60m IS NULL
                OR return_eod IS NULL
                OR max_favorable_60m IS NULL
                OR max_adverse_60m IS NULL
              )
            """,
            (target_date,),
        )
        return int(row["n"] or 0) if row else 0

    def rejected_outcome_bad_excursion_count(self, target_date: str) -> int:
        row = self._fetchone(
            """
            SELECT COUNT(*) AS n
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
              AND label_status IN ('labeled', 'partial')
              AND (
                   max_favorable_60m < -0.000001
                OR max_adverse_60m > 0.000001
              )
            """,
            (target_date,),
        )
        return int(row["n"] or 0) if row else 0

    def rejected_outcome_partial_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT trade_id, timestamp, partial_reason, return_60m
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
              AND label_status = 'partial'
            """,
            (target_date,),
        )

    def rejected_outcome_category_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT
                CASE
                  WHEN instr(rejection_reason, ':') > 0
                    THEN substr(rejection_reason, 1, instr(rejection_reason, ':') - 1)
                  ELSE COALESCE(rejection_reason, 'unknown')
                END AS category,
                COUNT(*) AS n,
                AVG(return_15m) AS avg_return_15m,
                AVG(max_favorable_60m) AS avg_mfe_60m
            FROM rejected_signal_outcomes
            WHERE substr(timestamp, 1, 10) = ?
            GROUP BY category
            ORDER BY n DESC, category
            LIMIT 12
            """,
            (target_date,),
        )

    def recent_market_date_rows(self, table_name: str) -> list[sqlite3.Row]:
        return self._fetchall(
            f"""
            SELECT market_date, COUNT(*) AS n
            FROM {table_name}
            GROUP BY market_date
            ORDER BY market_date DESC
            LIMIT 7
            """
        )

    def prediction_confidence_rows(self, target_date: str) -> list[sqlite3.Row]:
        return self._fetchall(
            """
            SELECT COALESCE(confidence, 'missing') AS confidence, COUNT(*) AS n
            FROM daily_symbol_predictions
            WHERE market_date = ?
            GROUP BY COALESCE(confidence, 'missing')
            ORDER BY confidence
            """,
            (target_date,),
        )

    def intelligence_freshness_row(self, target_date: str) -> sqlite3.Row | None:
        return self._fetchone(
            """
            SELECT
              (SELECT MAX(created_at)
               FROM daily_symbol_events
               WHERE market_date = ?) AS latest_event_at,
              (SELECT MAX(updated_at)
               FROM daily_symbol_context
               WHERE market_date = ?) AS latest_context_at,
              (SELECT MAX(updated_at)
               FROM daily_symbol_predictions
               WHERE market_date = ?) AS latest_prediction_at
            """,
            (target_date, target_date, target_date),
        )
