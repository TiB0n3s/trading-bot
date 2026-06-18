from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any, Callable


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not _table_exists(con, table):
        return set()
    return {row["name"] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


def _optional_column(
    columns: set[str], table_alias: str, column: str, fallback: str = "NULL"
) -> str:
    return f"{table_alias}.{column}" if column in columns else f"{fallback} AS {column}"


def _optional_alias(
    columns: set[str],
    table_alias: str,
    column: str,
    alias: str,
    fallback: str = "NULL",
) -> str:
    return f"{table_alias}.{column} AS {alias}" if column in columns else f"{fallback} AS {alias}"


class MlExportRepository:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)

    def fetch_rows(
        self,
        where_sql: str,
        params: tuple[Any, ...],
        *,
        row_callback: Callable[[sqlite3.Row], None] | None = None,
        chunk_size: int = 1000,
    ) -> list[sqlite3.Row]:
        with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            required = ("feature_snapshots", "labeled_setups")
            missing = [t for t in required if not _table_exists(con, t)]
            if missing:
                raise SystemExit(f"Missing required table(s): {', '.join(missing)}")
            fs_columns = _table_columns(con, "feature_snapshots")
            ls_columns = _table_columns(con, "labeled_setups")
            bp_columns = _table_columns(con, "bar_pattern_features")
            ds_columns = _table_columns(con, "decision_snapshots")
            es_columns = _table_columns(con, "exit_snapshots")
            bar_pattern_join = ""
            if bp_columns:
                bar_pattern_join = """
                LEFT JOIN bar_pattern_features bp
                  ON bp.symbol = fs.symbol
                 AND bp.bar_timestamp = fs.timestamp
                 AND bp.timeframe = '1m'
                 AND bp.rowid = (
                    SELECT MAX(bp2.rowid)
                    FROM bar_pattern_features bp2
                    WHERE bp2.symbol = fs.symbol
                      AND bp2.bar_timestamp = fs.timestamp
                      AND bp2.timeframe = '1m'
                 )
                """

            exit_snapshot_join = ""
            realized_exit_label_status = (
                "'excluded_no_realized_exit_snapshot' AS realized_exit_label_status"
            )
            realized_exit_label_version = "NULL AS realized_exit_label_version"
            exit_policy_version = "NULL AS exit_policy_version"
            position_manager_version = "NULL AS position_manager_version"
            canonical_exit_version = "NULL AS canonical_exit_version"
            if {"id", "symbol", "decision_time"} <= ds_columns and {
                "id",
                "decision_snapshot_id",
            } <= es_columns:
                exit_snapshot_join = """
                LEFT JOIN decision_snapshots ds
                  ON ds.symbol = fs.symbol
                 AND ds.decision_time = fs.timestamp
                LEFT JOIN exit_snapshots es
                  ON es.decision_snapshot_id = ds.id
                """
                has_exit_versions = {
                    "realized_exit_label_version",
                    "exit_policy_version",
                    "position_manager_version",
                } <= es_columns
                realized_exit_label_status = (
                    """
                    CASE
                        WHEN es.id IS NULL
                            THEN 'excluded_no_realized_exit_snapshot'
                        WHEN es.realized_exit_label_version IS NULL
                          OR es.exit_policy_version IS NULL
                          OR es.position_manager_version IS NULL
                            THEN 'excluded_missing_realized_exit_version'
                        ELSE 'versioned_realized_exit_observe_only'
                    END AS realized_exit_label_status
                    """
                    if has_exit_versions
                    else "'excluded_missing_realized_exit_version' AS realized_exit_label_status"
                )
                realized_exit_label_version = _optional_column(
                    es_columns, "es", "realized_exit_label_version"
                )
                exit_policy_version = _optional_column(es_columns, "es", "exit_policy_version")
                position_manager_version = _optional_column(
                    es_columns, "es", "position_manager_version"
                )
                canonical_exit_version = _optional_column(
                    es_columns, "es", "canonical_exit_version"
                )

            if "ret_fwd_60m" in ls_columns:
                horizon_status_case = """
                    CASE
                        WHEN ls.snapshot_id IS NULL
                            THEN 'unlabeled'
                        WHEN ls.ret_fwd_5m IS NULL
                         AND ls.ret_fwd_15m IS NULL
                         AND ls.ret_fwd_30m IS NULL
                         AND ls.ret_fwd_60m IS NULL
                            THEN 'incomplete'
                        WHEN ls.ret_fwd_60m IS NULL
                            THEN 'partial_near_close'
                        ELSE 'complete'
                    END AS label_horizon_status
                """
                label_target_family = "'fixed_horizon_v2_60m_action_mfe_mae' AS label_target_family"
            else:
                horizon_status_case = """
                    CASE
                        WHEN ls.snapshot_id IS NULL
                            THEN 'unlabeled'
                        WHEN ls.ret_fwd_5m IS NULL
                         AND ls.ret_fwd_15m IS NULL
                         AND ls.ret_fwd_30m IS NULL
                            THEN 'incomplete'
                        WHEN ls.ret_fwd_30m IS NULL
                            THEN 'partial_near_close'
                        ELSE 'complete'
                    END AS label_horizon_status
                """
                label_target_family = "'fixed_horizon_v1' AS label_target_family"

            query = f"""
                SELECT
                    fs.id AS snapshot_id,
                    substr(fs.timestamp, 1, 10) AS snapshot_date,
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
                    {_optional_column(fs_columns, "fs", "feature_available_at", "fs.timestamp")},
                    {_optional_column(fs_columns, "fs", "feature_generated_at", "fs.timestamp")},
                    {_optional_column(fs_columns, "fs", "feature_age_seconds", "0")},
                    {_optional_column(fs_columns, "fs", "source", "'feature_snapshots_legacy'")},
                    {_optional_column(fs_columns, "fs", "is_stale", "0")},
                    {_optional_column(fs_columns, "fs", "staleness_reason")},
                    fs.bar_timeframe,
                    fs.bar_count,
                    fs.setup_label,
                    fs.setup_recommendation,
                    fs.setup_score,
                    fs.setup_confidence,
                    fs.setup_key,
                    {_optional_alias(bp_columns, "bp", "feature_version", "bar_pattern_feature_version")},
                    {_optional_column(bp_columns, "bp", "candle_body_pct")},
                    {_optional_column(bp_columns, "bp", "upper_wick_pct")},
                    {_optional_column(bp_columns, "bp", "lower_wick_pct")},
                    {_optional_column(bp_columns, "bp", "upper_lower_wick_ratio")},
                    {_optional_column(bp_columns, "bp", "close_location")},
                    {_optional_column(bp_columns, "bp", "range_atr_ratio")},
                    {_optional_column(bp_columns, "bp", "atr_20_pct")},
                    {_optional_column(bp_columns, "bp", "volume_ratio_20")},
                    {_optional_column(bp_columns, "bp", "volume_profile_poc_dist_pct")},
                    {_optional_column(bp_columns, "bp", "volume_profile_vah_dist_pct")},
                    {_optional_column(bp_columns, "bp", "volume_profile_val_dist_pct")},
                    {_optional_column(bp_columns, "bp", "volume_profile_hvn_dist_pct")},
                    {_optional_column(bp_columns, "bp", "volume_profile_lvn_dist_pct")},
                    {_optional_column(bp_columns, "bp", "volume_profile_poc_volume_zscore")},
                    {_optional_column(bp_columns, "bp", "volume_profile_total_volume_zscore")},
                    {_optional_column(bp_columns, "bp", "volume_profile_value_area_width_pct")},
                    {_optional_column(bp_columns, "bp", "volume_profile_close_position")},
                    {_optional_column(bp_columns, "bp", "volume_profile_low_volume_zone")},
                    {_optional_column(bp_columns, "bp", "volume_profile_bin_00")},
                    {_optional_column(bp_columns, "bp", "volume_profile_bin_01")},
                    {_optional_column(bp_columns, "bp", "volume_profile_bin_02")},
                    {_optional_column(bp_columns, "bp", "volume_profile_bin_03")},
                    {_optional_column(bp_columns, "bp", "volume_profile_bin_04")},
                    {_optional_column(bp_columns, "bp", "volume_profile_bin_05")},
                    {_optional_column(bp_columns, "bp", "volume_profile_bin_06")},
                    {_optional_column(bp_columns, "bp", "volume_profile_bin_07")},
                    {_optional_column(bp_columns, "bp", "volume_profile_bin_08")},
                    {_optional_column(bp_columns, "bp", "volume_profile_bin_09")},
                    {_optional_column(bp_columns, "bp", "volume_profile_bin_10")},
                    {_optional_column(bp_columns, "bp", "volume_profile_bin_11")},
                    {_optional_column(bp_columns, "bp", "volume_profile_bin_12")},
                    {_optional_column(bp_columns, "bp", "volume_profile_bin_13")},
                    {_optional_column(bp_columns, "bp", "volume_profile_bin_14")},
                    {_optional_column(bp_columns, "bp", "volume_profile_bin_15")},
                    {_optional_column(bp_columns, "bp", "volume_profile_bin_16")},
                    {_optional_column(bp_columns, "bp", "volume_profile_bin_17")},
                    {_optional_column(bp_columns, "bp", "volume_profile_bin_18")},
                    {_optional_column(bp_columns, "bp", "volume_profile_bin_19")},
                    {_optional_column(bp_columns, "bp", "pressure_return_3")},
                    {_optional_column(bp_columns, "bp", "pressure_return_8")},
                    {_optional_column(bp_columns, "bp", "volume_weighted_pressure_3")},
                    {_optional_column(bp_columns, "bp", "volume_delta")},
                    {_optional_column(bp_columns, "bp", "institutional_volume_delta")},
                    {_optional_column(bp_columns, "bp", "cumulative_volume_delta")},
                    {_optional_column(bp_columns, "bp", "cvd_price_corr_20")},
                    {_optional_column(bp_columns, "bp", "cvd_divergence_label")},
                    {_optional_column(bp_columns, "bp", "vpin_toxicity_20")},
                    {_optional_column(bp_columns, "bp", "fractional_diff_close_045")},
                    {_optional_column(bp_columns, "bp", "fractional_diff_zscore_20")},
                    {_optional_column(bp_columns, "bp", "trend_scan_label")},
                    {_optional_column(bp_columns, "bp", "trend_scan_tstat")},
                    {_optional_column(bp_columns, "bp", "trend_scan_bars")},
                    {_optional_column(bp_columns, "bp", "trend_scan_return_pct")},
                    {_optional_column(bp_columns, "bp", "trend_scan_reason")},
                    {_optional_alias(bp_columns, "bp", "pattern_label", "bar_pattern_label")},
                    {_optional_alias(bp_columns, "bp", "pattern_score", "bar_pattern_score")},
                    {_optional_alias(bp_columns, "bp", "opportunity_action", "bar_opportunity_action")},
                    {_optional_alias(bp_columns, "bp", "opportunity_quality", "bar_opportunity_quality")},
                    {_optional_alias(bp_columns, "bp", "long_opportunity_score", "bar_long_opportunity_score")},
                    {_optional_alias(bp_columns, "bp", "sell_opportunity_score", "bar_sell_opportunity_score")},
                    ls.future_price_5m,
                    ls.future_price_15m,
                    ls.future_price_30m,
                    {_optional_column(ls_columns, "ls", "future_price_60m")},
                    ls.ret_fwd_5m,
                    ls.ret_fwd_15m,
                    ls.ret_fwd_30m,
                    {_optional_column(ls_columns, "ls", "ret_fwd_60m")},
                    ls.max_up_15m,
                    ls.max_down_15m,
                    {_optional_column(ls_columns, "ls", "max_up_60m")},
                    {_optional_column(ls_columns, "ls", "max_down_60m")},
                    {_optional_column(ls_columns, "ls", "action_direction")},
                    {_optional_column(ls_columns, "ls", "action_mfe_60m_pct")},
                    {_optional_column(ls_columns, "ls", "action_mae_60m_pct")},
                    ls.outcome_label,
                    {_optional_column(bp_columns, "bp", "triple_barrier_label")},
                    {_optional_column(bp_columns, "bp", "triple_barrier_reason")},
                    {_optional_column(bp_columns, "bp", "triple_barrier_bars_to_event")},
                    {_optional_column(bp_columns, "bp", "triple_barrier_profit_pct")},
                    {_optional_column(bp_columns, "bp", "triple_barrier_stop_pct")},
                    c.bias AS context_bias,
                    c.confidence AS context_confidence,
                    c.risk_level AS context_risk_level,
                    c.entry_quality AS context_entry_quality,
                    c.catalyst_score AS context_catalyst_score,
                    c.relative_strength_score AS context_relative_strength_score,
                    c.sector_alignment AS context_sector_alignment,
                    c.index_alignment AS context_index_alignment,
                    p.prediction_score,
                    p.probability_of_profit,
                    p.probability_of_order,
                    p.expected_pnl,
                    p.confidence AS prediction_confidence,
                    p.sample_size AS prediction_sample_size,
                    {horizon_status_case},
                    {label_target_family},
                    {realized_exit_label_status},
                    {realized_exit_label_version},
                    {exit_policy_version},
                    {position_manager_version},
                    {canonical_exit_version}
                FROM feature_snapshots fs
                LEFT JOIN labeled_setups ls
                  ON ls.snapshot_id = fs.id
                {bar_pattern_join}
                {exit_snapshot_join}
                LEFT JOIN daily_symbol_context c
                  ON c.market_date = substr(fs.timestamp, 1, 10)
                 AND c.symbol = fs.symbol
                LEFT JOIN daily_symbol_predictions p
                  ON p.market_date = substr(fs.timestamp, 1, 10)
                 AND p.symbol = fs.symbol
                WHERE {where_sql}
                ORDER BY fs.timestamp, fs.symbol, fs.id
            """
            cursor = con.execute(query, params)
            if row_callback is not None:
                while True:
                    rows = cursor.fetchmany(max(1, int(chunk_size)))
                    if not rows:
                        break
                    for row in rows:
                        row_callback(row)
                return []
            return cursor.fetchall()
