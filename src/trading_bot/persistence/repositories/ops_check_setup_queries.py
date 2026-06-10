from __future__ import annotations

import sqlite3


class OpsCheckSetupQueriesMixin:
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

    def pattern_learning_matched_rows(self, target_date: str) -> list[sqlite3.Row]:
        if not self.table_exists("matched_trades"):
            return []

        columns = self.table_columns("matched_trades")

        def expr(name: str, alias: str | None = None) -> str:
            alias = alias or name
            return name if name in columns else f"NULL AS {alias}"

        return self._fetchall(
            f"""
            SELECT
                id,
                symbol,
                entry_timestamp,
                exit_timestamp,
                realized_pnl_pct,
                realized_pnl,
                won,
                holding_minutes,
                {expr("mfe_pct")},
                {expr("capture_ratio")},
                {expr("max_adverse_excursion_pct")},
                {expr("setup_label")},
                {expr("setup_policy_action")},
                {expr("ml_prediction_bucket")},
                {expr("ml_prediction_score")},
                {expr("session_trend_label")},
                {expr("buy_opportunity_recommendation")},
                {expr("exit_reason")},
                {expr("entry_source")},
                {expr("signal_source")}
            FROM matched_trades
            WHERE DATE(COALESCE(exit_timestamp, entry_timestamp)) = ?
            ORDER BY COALESCE(exit_timestamp, entry_timestamp) ASC, id ASC
            """,
            (target_date,),
        )

    def pattern_learning_candidate_rows(self, target_date: str) -> list[sqlite3.Row]:
        if not self.table_exists("candidate_universe"):
            return []
        return self._fetchall(
            """
            SELECT
                id,
                candidate_ts,
                symbol,
                action,
                candidate_kind,
                candidate_status,
                score,
                threshold,
                threshold_distance,
                decision,
                reason,
                source,
                setup_label,
                regime,
                session_phase,
                candidate_json
            FROM candidate_universe
            WHERE substr(candidate_ts, 1, 10) = ?
            ORDER BY candidate_ts ASC, id ASC
            """,
            (target_date,),
        )

    def pattern_learning_bar_pattern_rows(self, target_date: str) -> list[sqlite3.Row]:
        if not self.table_exists("bar_pattern_features"):
            return []

        columns = self.table_columns("bar_pattern_features")

        def expr(name: str, alias: str | None = None) -> str:
            alias = alias or name
            return name if name in columns else f"NULL AS {alias}"

        where_sql = "bar_timestamp >= ? AND bar_timestamp < date(?, '+1 day')"
        params = (target_date, target_date)

        return self._fetchall(
            f"""
            SELECT
                symbol,
                bar_timestamp,
                timeframe,
                {expr("pattern_label")},
                {expr("pattern_score")},
                {expr("opportunity_action")},
                {expr("opportunity_quality")},
                {expr("long_opportunity_score")},
                {expr("sell_opportunity_score")},
                {expr("forward_return_pct")},
                {expr("forward_mfe_pct")},
                {expr("forward_mae_pct")},
                {expr("candle_body_pct")},
                {expr("upper_wick_pct")},
                {expr("lower_wick_pct")},
                {expr("range_atr_ratio")},
                {expr("atr_20_pct")},
                {expr("bid_ask_spread_pct")},
                {expr("slippage_estimate_pct")},
                {expr("liquidity_sweep_risk")},
                {expr("pressure_return_3")},
                {expr("pressure_return_8")},
                {expr("volume_weighted_pressure_3")},
                {expr("volume_delta")},
                {expr("institutional_volume_delta")},
                {expr("cumulative_volume_delta")},
                {expr("cvd_price_corr_20")},
                {expr("cvd_divergence_label")},
                {expr("vpin_toxicity_20")},
                {expr("fractional_diff_close_045")},
                {expr("fractional_diff_zscore_20")},
                {expr("triple_barrier_label")},
                {expr("triple_barrier_reason")},
                {expr("triple_barrier_bars_to_event")},
                {expr("triple_barrier_profit_pct")},
                {expr("triple_barrier_stop_pct")},
                {expr("trend_scan_label")},
                {expr("trend_scan_tstat")},
                {expr("trend_scan_bars")},
                {expr("trend_scan_return_pct")},
                {expr("trend_scan_reason")},
                {expr("horizon_bars")},
                {expr("feature_version")},
                {expr("runtime_effect")}
            FROM bar_pattern_features
            WHERE {where_sql}
            ORDER BY bar_timestamp ASC, symbol ASC
            """,
            params,
        )

    def decision_authority_rows(self, target_date: str) -> list[sqlite3.Row]:
        if not self.table_exists("decision_snapshots"):
            return []
        columns = self.table_columns("decision_snapshots")
        if "account_state_json" not in columns:
            return []
        canonical_expr = (
            "canonical_intelligence_json"
            if "canonical_intelligence_json" in columns
            else "NULL AS canonical_intelligence_json"
        )
        return self._fetchall(
            f"""
            SELECT
                id,
                decision_time,
                symbol,
                action,
                approved,
                final_decision,
                rejection_reason,
                account_state_json,
                {canonical_expr}
            FROM decision_snapshots
            WHERE substr(decision_time, 1, 10) = ?
              AND LOWER(COALESCE(action, '')) IN ('buy', 'sell')
            ORDER BY decision_time ASC, id ASC
            """,
            (target_date,),
        )
