"""Training reads for rejected-signal counterfactual learning."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from db import DB_PATH
from repositories.training_data_repo import SNAPSHOT_JOIN_FEATURE_VERSION_ALIASES


class CounterfactualTrainingRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _table_exists(con: sqlite3.Connection, table: str) -> bool:
        return (
            con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
            is not None
        )

    @staticmethod
    def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
        if not CounterfactualTrainingRepository._table_exists(con, table):
            return set()
        return {row["name"] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}

    @staticmethod
    def _opt(columns: set[str], alias: str, column: str, fallback: str = "NULL") -> str:
        return f"{alias}.{column} AS {column}" if column in columns else f"{fallback} AS {column}"

    @staticmethod
    def _bp_version_filter(columns: set[str]) -> str:
        if "feature_version" not in columns:
            return ""
        values = ", ".join(f"'{value}'" for value in SNAPSHOT_JOIN_FEATURE_VERSION_ALIASES)
        return f"AND bp2.feature_version IN ({values})"

    def fetch_rejected_counterfactual_rows(
        self,
        *,
        start_date: str,
        end_date: str,
        limit: int = 5000,
    ) -> list[dict[str, Any]]:
        """Return point-in-time rejected-signal outcomes plus live-time features."""
        if not self.db_path.exists():
            return []
        with self._connect() as con:
            required = ("rejected_signal_outcomes", "feature_snapshots")
            if any(not self._table_exists(con, table) for table in required):
                return []
            fs_cols = self._table_columns(con, "feature_snapshots")
            bp_cols = self._table_columns(con, "bar_pattern_features")
            has_bp = bool(bp_cols)
            bp_version_filter = self._bp_version_filter(bp_cols)
            bp_join = ""
            if has_bp:
                bp_join = f"""
                LEFT JOIN bar_pattern_features bp
                  ON bp.rowid = (
                    SELECT MAX(bp2.rowid)
                    FROM bar_pattern_features bp2
                    WHERE bp2.symbol = rso.symbol
                      AND bp2.timeframe = '1m'
                      AND datetime(bp2.bar_timestamp) <= datetime(rso.timestamp)
                      AND datetime(bp2.bar_timestamp) >= datetime(rso.timestamp, '-120 seconds')
                      {bp_version_filter}
                  )
                """

            query = f"""
                WITH base_rso AS (
                    SELECT *
                    FROM rejected_signal_outcomes
                    WHERE lower(action) = 'buy'
                      AND lower(label_status) IN ('labeled', 'completed')
                      AND substr(timestamp, 1, 10) BETWEEN ? AND ?
                    ORDER BY timestamp ASC, trade_id ASC
                    LIMIT ?
                )
                SELECT
                    rso.trade_id,
                    rso.timestamp,
                    rso.symbol,
                    rso.action,
                    rso.signal_price,
                    rso.rejection_reason,
                    rso.return_5m AS rejected_return_5m,
                    rso.return_15m AS rejected_return_15m,
                    rso.return_30m AS rejected_return_30m,
                    rso.return_60m AS rejected_return_60m,
                    rso.return_eod AS rejected_return_eod,
                    rso.max_favorable_60m,
                    rso.max_adverse_60m,
                    rso.label_status,
                    rso.partial_reason,
                    rso.decision_snapshot_id,
                    rso.canonical_intelligence_json,
                    fs.id AS feature_snapshot_id,
                    fs.ret_1m,
                    fs.ret_5m,
                    fs.ret_15m,
                    fs.range_pos_15m,
                    fs.distance_from_vwap,
                    fs.volume_ratio_5m,
                    fs.relative_strength_5m,
                    fs.spread_pct,
                    fs.setup_score,
                    {self._opt(fs_cols, "fs", "momentum_acceleration_pct")},
                    {self._opt(fs_cols, "fs", "volume_surge_ratio")},
                    {self._opt(fs_cols, "fs", "extension_from_recent_base_pct")},
                    {self._opt(fs_cols, "fs", "prior_session_return_pct")},
                    {"bp.id AS bar_pattern_id" if has_bp else "NULL AS bar_pattern_id"},
                    {"bp.candle_body_pct" if "candle_body_pct" in bp_cols else "NULL AS candle_body_pct"},
                    {"bp.close_location" if "close_location" in bp_cols else "NULL AS close_location"},
                    {"bp.range_atr_ratio" if "range_atr_ratio" in bp_cols else "NULL AS range_atr_ratio"},
                    {"bp.atr_20_pct" if "atr_20_pct" in bp_cols else "NULL AS atr_20_pct"},
                    {"bp.volume_ratio_20" if "volume_ratio_20" in bp_cols else "NULL AS volume_ratio_20"},
                    {"bp.volume_profile_poc_dist_pct" if "volume_profile_poc_dist_pct" in bp_cols else "NULL AS volume_profile_poc_dist_pct"},
                    {"bp.volume_profile_value_area_width_pct" if "volume_profile_value_area_width_pct" in bp_cols else "NULL AS volume_profile_value_area_width_pct"},
                    {"bp.volume_profile_close_position" if "volume_profile_close_position" in bp_cols else "NULL AS volume_profile_close_position"},
                    {"bp.volume_profile_low_volume_zone" if "volume_profile_low_volume_zone" in bp_cols else "NULL AS volume_profile_low_volume_zone"},
                    {"bp.volume_weighted_pressure_3" if "volume_weighted_pressure_3" in bp_cols else "NULL AS volume_weighted_pressure_3"},
                    {"bp.cumulative_volume_delta" if "cumulative_volume_delta" in bp_cols else "NULL AS cumulative_volume_delta"},
                    {"bp.cvd_price_corr_20" if "cvd_price_corr_20" in bp_cols else "NULL AS cvd_price_corr_20"},
                    {"bp.vpin_toxicity_20" if "vpin_toxicity_20" in bp_cols else "NULL AS vpin_toxicity_20"},
                    {"bp.fractional_diff_zscore_20" if "fractional_diff_zscore_20" in bp_cols else "NULL AS fractional_diff_zscore_20"},
                    {"bp.trend_scan_tstat" if "trend_scan_tstat" in bp_cols else "NULL AS trend_scan_tstat"},
                    {"bp.pattern_score" if "pattern_score" in bp_cols else "NULL AS pattern_score"}
                FROM base_rso rso
                LEFT JOIN feature_snapshots fs
                  ON fs.rowid = (
                    SELECT MAX(fs2.rowid)
                    FROM feature_snapshots fs2
                    WHERE fs2.symbol = rso.symbol
                      AND datetime(fs2.timestamp) <= datetime(rso.timestamp)
                      AND datetime(fs2.timestamp) >= datetime(rso.timestamp, '-180 seconds')
                  )
                {bp_join}
                ORDER BY rso.timestamp ASC, rso.trade_id ASC
            """
            rows = con.execute(query, (start_date, end_date, int(limit))).fetchall()
        return [dict(row) for row in rows]
