from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from repositories.ops_check_conviction_queries import OpsCheckConvictionQueriesMixin
from repositories.ops_check_excursion_queries import OpsCheckExcursionQueriesMixin
from repositories.ops_check_intelligence_queries import OpsCheckIntelligenceQueriesMixin
from repositories.ops_check_rejection_queries import OpsCheckRejectionQueriesMixin
from repositories.ops_check_setup_queries import OpsCheckSetupQueriesMixin


class OpsCheckRepository(
    OpsCheckSetupQueriesMixin,
    OpsCheckExcursionQueriesMixin,
    OpsCheckConvictionQueriesMixin,
    OpsCheckRejectionQueriesMixin,
    OpsCheckIntelligenceQueriesMixin,
):
    def __init__(self, db_path: Path):
        self.db_path = db_path

    def exists(self) -> bool:
        return self.db_path.exists()

    def table_exists(self, table_name: str) -> bool:
        row = self._fetchone(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        )
        return row is not None

    def table_columns(self, table_name: str) -> set[str]:
        rows = self._fetchall(f"PRAGMA table_info({table_name})")
        return {row["name"] for row in rows}

    def table_count(
        self,
        table_name: str,
        where_sql: str = "",
        params: tuple[Any, ...] = (),
    ) -> int | None:
        if not self.table_exists(table_name):
            return None

        sql = f"SELECT COUNT(*) AS n FROM {table_name}"
        if where_sql:
            sql += f" WHERE {where_sql}"
        row = self._fetchone(sql, params)
        return int(row["n"] or 0) if row else 0

    def _fetchall(self, sql: str, params: tuple[Any, ...] = ()) -> list[sqlite3.Row]:
        with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            return con.execute(sql, params).fetchall()

    def _fetchone(self, sql: str, params: tuple[Any, ...] = ()) -> sqlite3.Row | None:
        with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            return con.execute(sql, params).fetchone()
