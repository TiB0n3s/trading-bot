"""Repository boundary for research/training data access."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from db import DB_PATH
from services.bar_pattern_feature_service import BAR_PATTERN_FEATURE_VERSION


SNAPSHOT_JOIN_FEATURE_VERSION_ALIASES = (
    BAR_PATTERN_FEATURE_VERSION,
    "v4",
    "efi_pvt_orderflow_math_bar_pattern_v3",
)


class TrainingDataRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)

    def _connect(self):
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _table_exists(con: sqlite3.Connection, table: str) -> bool:
        row = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None

    def table_count(
        self,
        table: str,
        where_sql: str = "",
        params: tuple[Any, ...] = (),
    ) -> int | None:
        with self._connect() as con:
            if not self._table_exists(con, table):
                return None
            sql = f"SELECT COUNT(*) AS n FROM {table}"
            if where_sql:
                sql += f" WHERE {where_sql}"
            return int(con.execute(sql, params).fetchone()["n"] or 0)

    def min_max(self, table: str, column: str) -> dict[str, Any]:
        with self._connect() as con:
            if not self._table_exists(con, table):
                return {"min": None, "max": None}
            row = con.execute(
                f"SELECT MIN({column}) AS min_value, MAX({column}) AS max_value FROM {table}"
            ).fetchone()
        return {"min": row["min_value"], "max": row["max_value"]}

    def distinct_feature_snapshot_symbols(
        self,
        where_sql: str = "",
        params: tuple[Any, ...] = (),
    ) -> int:
        with self._connect() as con:
            if not self._table_exists(con, "feature_snapshots"):
                return 0
            where = f"WHERE {where_sql}" if where_sql else ""
            row = con.execute(
                f"SELECT COUNT(DISTINCT symbol) AS n FROM feature_snapshots {where}",
                params,
            ).fetchone()
        return int(row["n"] or 0)

    def brain_source_rows(
        self,
        where_sql: str,
        params: tuple[Any, ...],
    ) -> list[sqlite3.Row]:
        with self._connect() as con:
            if not self._table_exists(con, "feature_snapshots"):
                return []

            event_count = "0"
            if self._table_exists(con, "daily_symbol_events"):
                event_count = """
                    (
                        SELECT COUNT(*)
                        FROM daily_symbol_events e
                        WHERE e.market_date = substr(fs.timestamp, 1, 10)
                          AND e.symbol = fs.symbol
                    )
                """

            has_labels = self._table_exists(con, "labeled_setups")
            has_context = self._table_exists(con, "daily_symbol_context")
            has_predictions = self._table_exists(con, "daily_symbol_predictions")
            has_bar_patterns = self._table_exists(con, "bar_pattern_features")
            bp_cols = self._table_columns(con, "bar_pattern_features")
            bp_version_filter = self._bar_pattern_version_filter(bp_cols)

            label_join = """
                LEFT JOIN labeled_setups ls
                  ON ls.snapshot_id = fs.id
            """ if has_labels else ""
            context_join = """
                LEFT JOIN daily_symbol_context c
                  ON c.market_date = substr(fs.timestamp, 1, 10)
                 AND c.symbol = fs.symbol
            """ if has_context else ""
            prediction_join = """
                LEFT JOIN daily_symbol_predictions p
                  ON p.market_date = substr(fs.timestamp, 1, 10)
                 AND p.symbol = fs.symbol
            """ if has_predictions else ""
            bar_pattern_join = f"""
                LEFT JOIN bar_pattern_features bp
                  ON bp.rowid = (
                    SELECT MAX(bp2.rowid)
                    FROM bar_pattern_features bp2
                    WHERE bp2.symbol = fs.symbol
                      AND bp2.timeframe = '1m'
                      AND bp2.bar_timestamp <= strftime('%Y-%m-%dT%H:%M:%S', fs.timestamp) || '+00:00'
                      AND bp2.bar_timestamp >= strftime('%Y-%m-%dT%H:%M:%S', datetime(fs.timestamp, '-90 seconds')) || '+00:00'
                      {bp_version_filter}
                 )
            """ if has_bar_patterns else ""

            query = f"""
                SELECT
                    fs.*,
                    substr(fs.timestamp, 1, 10) AS snapshot_date,
                    {event_count} AS event_count,
                    {('ls.outcome_label' if has_labels else 'NULL')} AS outcome_label,
                    {('ls.ret_fwd_15m' if has_labels else 'NULL')} AS ret_fwd_15m,
                    {('ls.ret_fwd_30m' if has_labels else 'NULL')} AS ret_fwd_30m,
                    {('c.bias' if has_context else 'NULL')} AS context_bias,
                    {('c.confidence' if has_context else 'NULL')} AS context_confidence,
                    {('c.risk_level' if has_context else 'NULL')} AS context_risk_level,
                    {('c.entry_quality' if has_context else 'NULL')} AS context_entry_quality,
                    {('c.catalyst_score' if has_context else 'NULL')} AS context_catalyst_score,
                    {('c.relative_strength_score' if has_context else 'NULL')} AS context_relative_strength_score,
                    {('p.prediction_score' if has_predictions else 'NULL')} AS prediction_score,
                    {('p.confidence' if has_predictions else 'NULL')} AS prediction_confidence,
                    {('p.sample_size' if has_predictions else 'NULL')} AS prediction_sample_size,
                    {('p.trend_label' if has_predictions else 'NULL')} AS prediction_trend_label,
                    {('p.timing_score' if has_predictions else 'NULL')} AS prediction_timing_score,
                    {('bp.pattern_label' if has_bar_patterns else 'NULL')} AS bar_pattern_label,
                    {('bp.pattern_score' if has_bar_patterns else 'NULL')} AS bar_pattern_score,
                    {('bp.candle_body_pct' if has_bar_patterns else 'NULL')} AS candle_body_pct,
                    {('bp.close_location' if has_bar_patterns else 'NULL')} AS close_location,
                    {('bp.range_atr_ratio' if has_bar_patterns else 'NULL')} AS range_atr_ratio,
                    {('bp.volume_weighted_pressure_3' if has_bar_patterns else 'NULL')} AS volume_weighted_pressure_3,
                    {('bp.volume_delta' if has_bar_patterns else 'NULL')} AS volume_delta,
                    {('bp.institutional_volume_delta' if has_bar_patterns else 'NULL')} AS institutional_volume_delta,
                    {('bp.cumulative_volume_delta' if has_bar_patterns else 'NULL')} AS cumulative_volume_delta,
                    {('bp.cvd_price_corr_20' if has_bar_patterns else 'NULL')} AS cvd_price_corr_20,
                    {('bp.vpin_toxicity_20' if has_bar_patterns else 'NULL')} AS vpin_toxicity_20,
                    {('bp.fractional_diff_close_045' if has_bar_patterns else 'NULL')} AS fractional_diff_close_045,
                    {('bp.fractional_diff_zscore_20' if has_bar_patterns else 'NULL')} AS fractional_diff_zscore_20,
                    {('bp.ema_12' if has_bar_patterns else 'NULL')} AS ema_12,
                    {('bp.ema_26' if has_bar_patterns else 'NULL')} AS ema_26,
                    {('bp.macd' if has_bar_patterns else 'NULL')} AS macd,
                    {('bp.macd_signal' if has_bar_patterns else 'NULL')} AS macd_signal,
                    {('bp.rsi_14' if has_bar_patterns else 'NULL')} AS rsi_14,
                    {('bp.triple_barrier_label' if has_bar_patterns else 'NULL')} AS triple_barrier_label,
                    {('bp.trend_scan_label' if has_bar_patterns else 'NULL')} AS trend_scan_label,
                    {('bp.trend_scan_tstat' if has_bar_patterns else 'NULL')} AS trend_scan_tstat
                FROM feature_snapshots fs
                {label_join}
                {context_join}
                {prediction_join}
                {bar_pattern_join}
                WHERE {where_sql}
                ORDER BY fs.timestamp, fs.symbol, fs.id
            """
            return con.execute(query, params).fetchall()

    @staticmethod
    def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
        if not con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?", (table,)
        ).fetchone():
            return set()
        return {
            row["name"]
            for row in con.execute(f"PRAGMA table_info({table})").fetchall()
        }

    @staticmethod
    def _opt(columns: set[str], alias: str, col: str, fallback: str = "NULL") -> str:
        return f"{alias}.{col}" if col in columns else f"{fallback} AS {col}"

    @staticmethod
    def _bar_pattern_version_filter(columns: set[str]) -> str:
        if "feature_version" not in columns:
            return ""
        values = ", ".join(f"'{value}'" for value in SNAPSHOT_JOIN_FEATURE_VERSION_ALIASES)
        return f" AND bp2.feature_version IN ({values})"

    def raw_training_rows(
        self,
        start_date: str,
        end_date: str,
        *,
        limit: int | None = None,
    ) -> list[sqlite3.Row]:
        with self._connect() as con:
            for table in ("feature_snapshots", "labeled_setups"):
                if not self._table_exists(con, table):
                    raise RuntimeError(f"Required table missing: {table}")

            fs_cols = self._table_columns(con, "feature_snapshots")
            bp_cols = self._table_columns(con, "bar_pattern_features")
            bp_version_filter = self._bar_pattern_version_filter(bp_cols)
            opt = self._opt

            def bp_opt(col: str, alias: str | None = None, fallback: str = "NULL") -> str:
                alias = alias or col
                return f"bp.{col} AS {alias}" if col in bp_cols else f"{fallback} AS {alias}"

            bar_pattern_join = ""
            if bp_cols:
                bar_pattern_join = f"""
                LEFT JOIN bar_pattern_features bp
                  ON bp.rowid = (
                    SELECT MAX(bp2.rowid)
                    FROM bar_pattern_features bp2
                    WHERE bp2.symbol = fs.symbol
                      AND bp2.timeframe = '1m'
                      AND bp2.bar_timestamp <= strftime('%Y-%m-%dT%H:%M:%S', fs.timestamp) || '+00:00'
                      AND bp2.bar_timestamp >= strftime('%Y-%m-%dT%H:%M:%S', datetime(fs.timestamp, '-90 seconds')) || '+00:00'
                      {bp_version_filter}
                 )
                """
            limit_sql = ""
            if limit and limit > 0:
                limit_sql = f" LIMIT {int(limit)}"

            query = f"""
                WITH limited_fs AS (
                    SELECT *
                    FROM feature_snapshots
                    WHERE substr(timestamp, 1, 10) BETWEEN ? AND ?
                    ORDER BY timestamp, symbol, id
                    {limit_sql}
                )
                SELECT
                    fs.id                          AS snapshot_id,
                    substr(fs.timestamp, 1, 10)    AS snapshot_date,
                    fs.timestamp,
                    fs.symbol,
                    fs.last_price,
                    fs.ret_1m,
                    fs.ret_5m,
                    fs.ret_15m,
                    fs.range_pos_15m,
                    fs.distance_from_5m_high,
                    fs.distance_from_5m_low,
                    fs.distance_from_vwap,
                    fs.volume_ratio_5m,
                    fs.benchmark_symbol,
                    fs.benchmark_ret_5m,
                    fs.relative_strength_5m,
                    fs.spread_pct,
                    fs.market_session,
                    fs.macro_regime,
                    fs.market_bias,
                    fs.trend_direction,
                    fs.trend_strength,
                    {opt(fs_cols, 'fs', 'feature_available_at', 'fs.timestamp')},
                    {opt(fs_cols, 'fs', 'feature_generated_at', 'fs.timestamp')},
                    {opt(fs_cols, 'fs', 'feature_age_seconds', '0')},
                    {opt(fs_cols, 'fs', 'source', "'feature_snapshots_legacy'")},
                    {opt(fs_cols, 'fs', 'is_stale', '0')},
                    {opt(fs_cols, 'fs', 'staleness_reason')},
                    fs.bar_timeframe,
                    fs.bar_count,
                    fs.setup_label,
                    fs.setup_recommendation,
                    fs.setup_score,
                    fs.setup_confidence,
                    fs.setup_key,
                    {bp_opt('feature_version', 'bar_pattern_feature_version')},
                    {bp_opt('candle_body_pct')},
                    {bp_opt('upper_wick_pct')},
                    {bp_opt('lower_wick_pct')},
                    {bp_opt('upper_lower_wick_ratio')},
                    {bp_opt('close_location')},
                    {bp_opt('range_atr_ratio')},
                    {bp_opt('atr_20_pct')},
                    {bp_opt('volume_ratio_20')},
                    {bp_opt('pressure_return_3')},
                    {bp_opt('pressure_return_8')},
                    {bp_opt('volume_weighted_pressure_3')},
                    {bp_opt('volume_delta')},
                    {bp_opt('institutional_volume_delta')},
                    {bp_opt('cumulative_volume_delta')},
                    {bp_opt('cvd_price_corr_20')},
                    {bp_opt('cvd_divergence_label')},
                    {bp_opt('vpin_toxicity_20')},
                    {bp_opt('fractional_diff_close_045')},
                    {bp_opt('fractional_diff_zscore_20')},
                    {bp_opt('ema_12')},
                    {bp_opt('ema_26')},
                    {bp_opt('macd')},
                    {bp_opt('macd_signal')},
                    {bp_opt('rsi_14')},
                    {bp_opt('trend_scan_label')},
                    {bp_opt('trend_scan_tstat')},
                    {bp_opt('trend_scan_bars')},
                    {bp_opt('trend_scan_return_pct')},
                    {bp_opt('trend_scan_reason')},
                    {bp_opt('pattern_label', 'bar_pattern_label')},
                    {bp_opt('pattern_score', 'bar_pattern_score')},
                    {bp_opt('opportunity_action', 'bar_opportunity_action')},
                    {bp_opt('opportunity_quality', 'bar_opportunity_quality')},
                    {bp_opt('long_opportunity_score', 'bar_long_opportunity_score')},
                    {bp_opt('sell_opportunity_score', 'bar_sell_opportunity_score')},
                    ls.future_price_5m,
                    ls.future_price_15m,
                    ls.future_price_30m,
                    ls.ret_fwd_5m,
                    ls.ret_fwd_15m,
                    ls.ret_fwd_30m,
                    ls.max_up_15m,
                    ls.max_down_15m,
                    ls.outcome_label,
                    {bp_opt('triple_barrier_label')},
                    {bp_opt('triple_barrier_reason')},
                    {bp_opt('triple_barrier_bars_to_event')},
                    {bp_opt('triple_barrier_profit_pct')},
                    {bp_opt('triple_barrier_stop_pct')},
                    c.bias                         AS context_bias,
                    c.confidence                   AS context_confidence,
                    c.risk_level                   AS context_risk_level,
                    c.entry_quality                AS context_entry_quality,
                    c.catalyst_score               AS context_catalyst_score,
                    c.relative_strength_score      AS context_relative_strength_score,
                    c.sector_alignment             AS context_sector_alignment,
                    c.index_alignment              AS context_index_alignment,
                    p.prediction_score,
                    p.probability_of_profit,
                    p.probability_of_order,
                    p.expected_pnl,
                    p.confidence                   AS prediction_confidence,
                    p.sample_size                  AS prediction_sample_size,
                    CASE
                        WHEN ls.snapshot_id IS NULL           THEN 'unlabeled'
                        WHEN ls.ret_fwd_5m  IS NULL
                         AND ls.ret_fwd_15m IS NULL
                         AND ls.ret_fwd_30m IS NULL            THEN 'incomplete'
                        WHEN ls.ret_fwd_30m IS NULL            THEN 'partial_near_close'
                        ELSE 'complete'
                    END                            AS label_horizon_status,
                    'fixed_horizon_v1'             AS label_target_family,
                    'excluded_not_training_target' AS realized_exit_label_status,
                    NULL                           AS exit_policy_version,
                    NULL                           AS position_manager_version
                FROM limited_fs fs
                LEFT JOIN labeled_setups ls
                  ON ls.snapshot_id = fs.id
                {bar_pattern_join}
                LEFT JOIN daily_symbol_context c
                  ON c.market_date = substr(fs.timestamp, 1, 10)
                 AND c.symbol      = fs.symbol
                LEFT JOIN daily_symbol_predictions p
                  ON p.market_date = substr(fs.timestamp, 1, 10)
                 AND p.symbol      = fs.symbol
                ORDER BY fs.timestamp, fs.symbol, fs.id
            """
            return con.execute(query, (start_date, end_date)).fetchall()

    def pit_contract(self, required_fields: tuple[str, ...]) -> dict[str, Any]:
        result: dict[str, Any] = {
            "ok": False,
            "missing_feature_audit_fields": [],
            "stale_feature_snapshot_count": 0,
            "table_exists": False,
        }
        try:
            with self._connect() as con:
                if not self._table_exists(con, "feature_snapshots"):
                    return result
                result["table_exists"] = True
                present = self._table_columns(con, "feature_snapshots")
                missing = [field for field in required_fields if field not in present]
                result["missing_feature_audit_fields"] = missing
                if not missing:
                    result["stale_feature_snapshot_count"] = con.execute(
                        "SELECT COUNT(*) FROM feature_snapshots WHERE is_stale != 0"
                    ).fetchone()[0]
                result["ok"] = not missing
        except Exception as exc:
            result["error"] = str(exc)
        return result

    def manifest_source_summary(
        self,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any]:
        summary: dict[str, Any] = {
            "row_count": 0,
            "symbol_count": 0,
            "date_range": {"start": start_date, "end": end_date},
        }
        if not self.db_path.exists():
            return summary

        where_sql = ""
        params: tuple[str, ...] = ()
        if start_date and end_date:
            where_sql = "WHERE substr(timestamp, 1, 10) BETWEEN ? AND ?"
            params = (start_date, end_date)
        elif start_date or end_date:
            raise ValueError("Provide both start_date and end_date, or neither")

        with self._connect() as con:
            if not self._table_exists(con, "feature_snapshots"):
                return summary
            row = con.execute(
                f"""
                SELECT COUNT(*) AS rows, COUNT(DISTINCT symbol) AS symbols
                FROM feature_snapshots {where_sql}
                """,
                params,
            ).fetchone()
            summary["row_count"] = int(row["rows"] or 0)
            summary["symbol_count"] = int(row["symbols"] or 0)
            if not start_date and not end_date:
                range_row = con.execute(
                    """
                    SELECT
                        MIN(substr(timestamp, 1, 10)) AS start,
                        MAX(substr(timestamp, 1, 10)) AS end
                    FROM feature_snapshots
                    """
                ).fetchone()
                summary["date_range"] = {
                    "start": range_row["start"],
                    "end": range_row["end"],
                }
        return summary

    def replay_snapshot_rows(self, start_date: str, end_date: str) -> list[sqlite3.Row]:
        if not self.db_path.exists():
            return []
        with self._connect() as con:
            tables = {
                row[0]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "decision_snapshots" not in tables:
                return []
            return con.execute(
                """
                SELECT id, symbol, action, decision_time, final_decision, approved,
                       trade_id, rejection_reason, account_state_json
                FROM decision_snapshots
                WHERE action = 'buy'
                  AND substr(decision_time, 1, 10) BETWEEN ? AND ?
                ORDER BY decision_time, id
                """,
                (start_date, end_date),
            ).fetchall()

    def replay_realized_outcome_rows(self, start_date: str, end_date: str) -> list[sqlite3.Row]:
        if not self.db_path.exists():
            return []
        with self._connect() as con:
            if not (
                self._table_exists(con, "trades")
                and self._table_exists(con, "matched_trades")
            ):
                return []
            return con.execute(
                """
                SELECT
                    t.id AS trade_id,
                    t.symbol,
                    t.timestamp,
                    SUM(COALESCE(mt.realized_pnl, 0)) AS realized_pnl,
                    SUM(COALESCE(mt.qty, 0) * COALESCE(mt.entry_price, 0)) AS capital_at_risk,
                    COUNT(mt.id) AS matched_exit_count,
                    MIN(mt.exit_timestamp) AS first_exit_timestamp,
                    MAX(mt.exit_timestamp) AS last_exit_timestamp
                FROM trades t
                JOIN matched_trades mt
                  ON mt.symbol = t.symbol
                 AND mt.entry_timestamp = t.timestamp
                WHERE lower(t.action) = 'buy'
                  AND COALESCE(t.approved, 0) = 1
                  AND substr(t.timestamp, 1, 10) BETWEEN ? AND ?
                GROUP BY t.id, t.symbol, t.timestamp
                """,
                (start_date, end_date),
            ).fetchall()

    def replay_rejected_outcome_rows(self, start_date: str, end_date: str) -> list[sqlite3.Row]:
        if not self.db_path.exists():
            return []
        with self._connect() as con:
            if not self._table_exists(con, "rejected_signal_outcomes"):
                return []
            return con.execute(
                """
                SELECT trade_id, label_status, partial_reason,
                       return_5m, return_15m, return_30m, return_60m, return_eod,
                       max_favorable_60m, max_adverse_60m
                FROM rejected_signal_outcomes
                WHERE trade_id IS NOT NULL
                  AND lower(action) = 'buy'
                  AND substr(timestamp, 1, 10) BETWEEN ? AND ?
                """,
                (start_date, end_date),
            ).fetchall()
