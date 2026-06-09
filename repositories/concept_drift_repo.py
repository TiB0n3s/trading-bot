"""Repository reads for feature-distribution concept drift checks."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class ConceptDriftRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def table_exists(self, table_name: str) -> bool:
        with get_connection(self.db_path) as con:
            row = con.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = ?
                """,
                (table_name,),
            ).fetchone()
        return row is not None

    def table_columns(self, table_name: str) -> set[str]:
        if not self.table_exists(table_name):
            return set()
        with get_connection(self.db_path) as con:
            return {
                str(row["name"])
                for row in con.execute(f"PRAGMA table_info({table_name})").fetchall()
            }

    def feature_values(
        self,
        *,
        table_name: str,
        feature: str,
        start_date: str,
        end_date: str,
        limit: int = 50000,
    ) -> list[float]:
        if not self.table_exists(table_name):
            return []
        columns = self.table_columns(table_name)
        if feature not in columns:
            return []
        timestamp_col = "bar_timestamp" if "bar_timestamp" in columns else "timestamp"
        with get_connection(self.db_path) as con:
            rows = con.execute(
                f"""
                SELECT {feature} AS value
                FROM {table_name}
                WHERE {feature} IS NOT NULL
                  AND substr({timestamp_col}, 1, 10) BETWEEN ? AND ?
                ORDER BY {timestamp_col} DESC
                LIMIT ?
                """,
                (start_date, end_date, int(limit)),
            ).fetchall()
        values: list[float] = []
        for row in rows:
            try:
                value = float(row["value"])
            except Exception:
                continue
            if value == value:
                values.append(value)
        return values

    def bar_pattern_features_present(self) -> list[str]:
        return sorted(self.table_columns("bar_pattern_features"))

    def ensure_drift_regime_archive_table(self) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS drift_regime_archives (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    target_date TEXT NOT NULL,
                    baseline_start TEXT,
                    baseline_end TEXT,
                    recent_start TEXT,
                    recent_end TEXT,
                    severe_psi_threshold REAL,
                    max_psi REAL,
                    severe_drift INTEGER NOT NULL,
                    feature_distribution_json TEXT NOT NULL,
                    report_json TEXT NOT NULL,
                    source TEXT NOT NULL,
                    generated_at TEXT NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_drift_regime_archives_target_date
                ON drift_regime_archives(target_date)
                """
            )

    def archive_drift_regime(self, report: dict[str, Any]) -> int:
        self.ensure_drift_regime_archive_table()
        with get_connection(self.db_path) as con:
            cur = con.execute(
                """
                INSERT INTO drift_regime_archives (
                    target_date,
                    baseline_start,
                    baseline_end,
                    recent_start,
                    recent_end,
                    severe_psi_threshold,
                    max_psi,
                    severe_drift,
                    feature_distribution_json,
                    report_json,
                    source,
                    generated_at
                )
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    report.get("target_date"),
                    (report.get("baseline_window") or {}).get("start"),
                    (report.get("baseline_window") or {}).get("end"),
                    (report.get("recent_window") or {}).get("start"),
                    (report.get("recent_window") or {}).get("end"),
                    report.get("severe_psi_threshold"),
                    report.get("max_psi"),
                    1 if report.get("severe_drift") else 0,
                    json.dumps(report.get("features") or [], sort_keys=True),
                    json.dumps(report, sort_keys=True),
                    "concept_drift_psi_guardrail",
                    report.get("generated_at"),
                ),
            )
            return int(cur.lastrowid)
