"""Repository boundary for research/training data access."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from db import DB_PATH


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
