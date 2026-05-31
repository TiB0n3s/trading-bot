"""Repository boundary for strategy_intelligence_report.py reads."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class StrategyIntelligenceReportRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def table_columns(self, table: str) -> set[str]:
        with get_connection(self.db_path) as con:
            rows = con.execute(f"PRAGMA table_info({table})").fetchall()
        return {row["name"] for row in rows}

    def select_existing(
        self,
        table: str,
        wanted: list[str],
        where_sql: str,
        params: tuple[Any, ...],
    ) -> tuple[list[Any], list[str]]:
        cols = self.table_columns(table)
        selected = [col for col in wanted if col in cols]

        if not selected:
            return [], selected

        with get_connection(self.db_path) as con:
            rows = con.execute(
                f"""
                SELECT {", ".join(selected)}
                FROM {table}
                {where_sql}
                """,
                params,
            ).fetchall()

        return rows, selected
