"""Repository boundary for research export table reads."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable

from db import DB_PATH, get_connection


class ResearchExportRepository:
    """Read daily research datasets without leaking SQLite access to scripts."""

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = db_path or DB_PATH

    @staticmethod
    def _valid_identifier(name: str) -> bool:
        return bool(name) and all(ch.isalnum() or ch == "_" for ch in name)

    def table_exists(self, table: str) -> bool:
        if not self._valid_identifier(table):
            return False
        with get_connection(self.db_path) as con:
            return (
                con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (table,),
                ).fetchone()
                is not None
            )

    def table_columns(self, table: str) -> set[str]:
        if not self._valid_identifier(table) or not self.table_exists(table):
            return set()
        with get_connection(self.db_path) as con:
            return {row["name"] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}

    def rows_for_date(
        self,
        *,
        table: str,
        target_date: str,
        date_columns: Iterable[str],
        limit: int | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Return rows where any known timestamp/date column falls on target_date."""
        if not self._valid_identifier(table) or not self.table_exists(table):
            return [], []

        columns = self.table_columns(table)
        usable_date_columns = [
            col for col in date_columns if self._valid_identifier(col) and col in columns
        ]
        if not usable_date_columns:
            return [], []

        where = " OR ".join(f"substr({col}, 1, 10) = ?" for col in usable_date_columns)
        params: list[Any] = [target_date] * len(usable_date_columns)
        sql = f"SELECT * FROM {table} WHERE {where} ORDER BY rowid ASC"
        if limit is not None and limit > 0:
            sql += " LIMIT ?"
            params.append(int(limit))

        with get_connection(self.db_path) as con:
            rows = con.execute(sql, params).fetchall()
            return [dict(row) for row in rows], usable_date_columns
