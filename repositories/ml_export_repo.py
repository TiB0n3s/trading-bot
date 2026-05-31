from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any


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


def _optional_column(columns: set[str], table_alias: str, column: str, fallback: str = "NULL") -> str:
    return f"{table_alias}.{column}" if column in columns else f"{fallback} AS {column}"


class MlExportRepository:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)

    def fetch_rows(self, where_sql: str, params: tuple[Any, ...]) -> list[sqlite3.Row]:
        with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            required = ("feature_snapshots", "labeled_setups")
            missing = [t for t in required if not _table_exists(con, t)]
            if missing:
                raise SystemExit(f"Missing required table(s): {', '.join(missing)}")
            fs_columns = _table_columns(con, "feature_snapshots")

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
                    {_optional_column(fs_columns, 'fs', 'feature_available_at', 'fs.timestamp')},
                    {_optional_column(fs_columns, 'fs', 'feature_generated_at', 'fs.timestamp')},
                    {_optional_column(fs_columns, 'fs', 'feature_age_seconds', '0')},
                    {_optional_column(fs_columns, 'fs', 'source', "'feature_snapshots_legacy'")},
                    {_optional_column(fs_columns, 'fs', 'is_stale', '0')},
                    {_optional_column(fs_columns, 'fs', 'staleness_reason')},
                    fs.bar_timeframe,
                    fs.bar_count,
                    fs.setup_label,
                    fs.setup_recommendation,
                    fs.setup_score,
                    fs.setup_confidence,
                    fs.setup_key,
                    ls.future_price_5m,
                    ls.future_price_15m,
                    ls.future_price_30m,
                    ls.ret_fwd_5m,
                    ls.ret_fwd_15m,
                    ls.ret_fwd_30m,
                    ls.max_up_15m,
                    ls.max_down_15m,
                    ls.outcome_label,
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
                    END AS label_horizon_status,
                    'fixed_horizon_v1' AS label_target_family,
                    'excluded_not_training_target' AS realized_exit_label_status,
                    NULL AS exit_policy_version,
                    NULL AS position_manager_version
                FROM feature_snapshots fs
                LEFT JOIN labeled_setups ls
                  ON ls.snapshot_id = fs.id
                LEFT JOIN daily_symbol_context c
                  ON c.market_date = substr(fs.timestamp, 1, 10)
                 AND c.symbol = fs.symbol
                LEFT JOIN daily_symbol_predictions p
                  ON p.market_date = substr(fs.timestamp, 1, 10)
                 AND p.symbol = fs.symbol
                WHERE {where_sql}
                ORDER BY fs.timestamp, fs.symbol, fs.id
            """
            return con.execute(query, params).fetchall()
