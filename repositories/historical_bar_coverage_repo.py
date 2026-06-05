"""Repository reads for historical bar-pattern feature coverage."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from db import DB_PATH


class HistoricalBarCoverageRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)

    def exists(self) -> bool:
        return self.db_path.exists()

    def _connect(self):
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _table_exists(con: sqlite3.Connection, table: str) -> bool:
        row = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    def coverage_payload(
        self,
        *,
        start_date: str | None = None,
        end_date: str | None = None,
    ) -> dict[str, Any] | None:
        if not self.exists():
            return None
        with self._connect() as con:
            if not self._table_exists(con, "bar_pattern_features"):
                return {"table_exists": False}

            where = "WHERE timeframe = '1m'"
            params: list[str] = []
            if start_date:
                where += " AND substr(bar_timestamp, 1, 10) >= ?"
                params.append(start_date)
            if end_date:
                where += " AND substr(bar_timestamp, 1, 10) <= ?"
                params.append(end_date)

            summary = con.execute(
                f"""
                SELECT
                    COUNT(*) AS rows,
                    COUNT(DISTINCT symbol) AS symbols,
                    COUNT(DISTINCT substr(bar_timestamp, 1, 10)) AS market_dates,
                    MIN(bar_timestamp) AS min_ts,
                    MAX(bar_timestamp) AS max_ts,
                    SUM(CASE WHEN triple_barrier_label IS NOT NULL THEN 1 ELSE 0 END) AS triple_rows,
                    SUM(CASE WHEN trend_scan_label IS NOT NULL THEN 1 ELSE 0 END) AS trend_scan_rows,
                    SUM(CASE WHEN fractional_diff_zscore_20 IS NOT NULL THEN 1 ELSE 0 END) AS fractional_rows,
                    SUM(CASE WHEN vpin_toxicity_20 IS NOT NULL THEN 1 ELSE 0 END) AS vpin_rows,
                    SUM(CASE WHEN cumulative_volume_delta IS NOT NULL THEN 1 ELSE 0 END) AS cvd_rows
                FROM bar_pattern_features
                {where}
                """,
                params,
            ).fetchone()

            top_symbols = con.execute(
                f"""
                SELECT symbol, COUNT(*) AS rows,
                       MIN(bar_timestamp) AS min_ts,
                       MAX(bar_timestamp) AS max_ts
                FROM bar_pattern_features
                {where}
                GROUP BY symbol
                ORDER BY rows DESC, symbol
                LIMIT 12
                """,
                params,
            ).fetchall()

        return {
            "table_exists": True,
            "summary": dict(summary),
            "top_symbols": [dict(row) for row in top_symbols],
        }
