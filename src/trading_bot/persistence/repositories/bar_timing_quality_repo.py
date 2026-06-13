"""Persistence for derived entry/exit timing labels from bar outcomes."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class BarTimingQualityRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def init_table(self) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS bar_timing_quality_labels (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    bar_pattern_feature_id INTEGER NOT NULL,
                    symbol TEXT NOT NULL,
                    bar_timestamp TEXT NOT NULL,
                    timeframe TEXT NOT NULL,
                    bar_source TEXT,
                    feature_version TEXT,
                    entry_timing_label TEXT NOT NULL,
                    entry_timing_score REAL NOT NULL,
                    exit_timing_label TEXT NOT NULL,
                    exit_timing_score REAL NOT NULL,
                    forward_return_pct REAL,
                    forward_mfe_pct REAL,
                    forward_mae_pct REAL,
                    long_opportunity_score REAL,
                    sell_opportunity_score REAL,
                    horizon_bars INTEGER,
                    label_version TEXT NOT NULL,
                    runtime_effect TEXT NOT NULL,
                    reason TEXT,
                    generated_at TEXT NOT NULL,
                    feature_json TEXT,
                    UNIQUE(bar_pattern_feature_id, label_version)
                )
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bar_timing_quality_symbol_ts
                ON bar_timing_quality_labels(symbol, bar_timestamp)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bar_timing_quality_entry
                ON bar_timing_quality_labels(entry_timing_label, bar_timestamp)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_bar_timing_quality_exit
                ON bar_timing_quality_labels(exit_timing_label, bar_timestamp)
                """
            )

    def source_rows(
        self,
        *,
        target_date: str | None = None,
        limit: int | None = None,
        timeframe: str = "1m",
    ) -> list[dict[str, Any]]:
        self.init_table()
        where = ["timeframe = ?", "forward_return_pct IS NOT NULL"]
        params: list[Any] = [timeframe]
        if target_date:
            where.append("substr(bar_timestamp, 1, 10) = ?")
            params.append(target_date)
        limit_sql = f" LIMIT {int(limit)}" if limit and limit > 0 else ""
        with get_connection(self.db_path) as con:
            rows = con.execute(
                f"""
                SELECT
                    id AS bar_pattern_feature_id,
                    symbol,
                    bar_timestamp,
                    timeframe,
                    bar_source,
                    feature_version,
                    forward_return_pct,
                    forward_mfe_pct,
                    forward_mae_pct,
                    long_opportunity_score,
                    sell_opportunity_score,
                    horizon_bars,
                    pattern_label,
                    opportunity_action,
                    opportunity_quality,
                    triple_barrier_label,
                    trend_scan_label,
                    trend_scan_tstat,
                    feature_json
                FROM bar_pattern_features
                WHERE {" AND ".join(where)}
                ORDER BY bar_timestamp ASC, symbol ASC, id ASC
                {limit_sql}
                """,
                params,
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_labels(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        self.init_table()
        with get_connection(self.db_path) as con:
            con.executemany(
                """
                INSERT INTO bar_timing_quality_labels (
                    bar_pattern_feature_id, symbol, bar_timestamp, timeframe,
                    bar_source, feature_version, entry_timing_label,
                    entry_timing_score, exit_timing_label, exit_timing_score,
                    forward_return_pct, forward_mfe_pct, forward_mae_pct,
                    long_opportunity_score, sell_opportunity_score, horizon_bars,
                    label_version, runtime_effect, reason, generated_at, feature_json
                ) VALUES (
                    :bar_pattern_feature_id, :symbol, :bar_timestamp, :timeframe,
                    :bar_source, :feature_version, :entry_timing_label,
                    :entry_timing_score, :exit_timing_label, :exit_timing_score,
                    :forward_return_pct, :forward_mfe_pct, :forward_mae_pct,
                    :long_opportunity_score, :sell_opportunity_score, :horizon_bars,
                    :label_version, :runtime_effect, :reason, :generated_at,
                    :feature_json
                )
                ON CONFLICT(bar_pattern_feature_id, label_version)
                DO UPDATE SET
                    entry_timing_label = excluded.entry_timing_label,
                    entry_timing_score = excluded.entry_timing_score,
                    exit_timing_label = excluded.exit_timing_label,
                    exit_timing_score = excluded.exit_timing_score,
                    forward_return_pct = excluded.forward_return_pct,
                    forward_mfe_pct = excluded.forward_mfe_pct,
                    forward_mae_pct = excluded.forward_mae_pct,
                    long_opportunity_score = excluded.long_opportunity_score,
                    sell_opportunity_score = excluded.sell_opportunity_score,
                    horizon_bars = excluded.horizon_bars,
                    runtime_effect = excluded.runtime_effect,
                    reason = excluded.reason,
                    generated_at = excluded.generated_at,
                    feature_json = excluded.feature_json
                """,
                [
                    {
                        **row,
                        "feature_json": json.dumps(
                            row.get("feature_json") or {},
                            sort_keys=True,
                            separators=(",", ":"),
                        ),
                    }
                    for row in rows
                ],
            )
        return len(rows)

    def summary(self, *, target_date: str | None = None) -> dict[str, Any]:
        self.init_table()
        where = ""
        params: list[Any] = []
        if target_date:
            where = "WHERE substr(bar_timestamp, 1, 10) = ?"
            params.append(target_date)
        with get_connection(self.db_path) as con:
            total = con.execute(
                f"SELECT COUNT(*) AS n FROM bar_timing_quality_labels {where}",
                params,
            ).fetchone()
            entries = con.execute(
                f"""
                SELECT entry_timing_label AS label,
                       COUNT(*) AS rows,
                       AVG(entry_timing_score) AS avg_score,
                       AVG(forward_return_pct) AS avg_forward_return_pct,
                       AVG(forward_mfe_pct) AS avg_forward_mfe_pct,
                       AVG(forward_mae_pct) AS avg_forward_mae_pct
                FROM bar_timing_quality_labels
                {where}
                GROUP BY entry_timing_label
                ORDER BY rows DESC, label
                """,
                params,
            ).fetchall()
            exits = con.execute(
                f"""
                SELECT exit_timing_label AS label,
                       COUNT(*) AS rows,
                       AVG(exit_timing_score) AS avg_score,
                       AVG(forward_return_pct) AS avg_forward_return_pct,
                       AVG(forward_mfe_pct) AS avg_forward_mfe_pct,
                       AVG(forward_mae_pct) AS avg_forward_mae_pct
                FROM bar_timing_quality_labels
                {where}
                GROUP BY exit_timing_label
                ORDER BY rows DESC, label
                """,
                params,
            ).fetchall()
        return {
            "rows": int(total["n"] or 0),
            "entry_labels": [dict(row) for row in entries],
            "exit_labels": [dict(row) for row in exits],
        }
