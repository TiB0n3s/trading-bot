"""Repository helpers for analytics extension modules."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class AnalyticsExtRepository:
    def __init__(self, db_path: str | Path = DB_PATH):
        self.db_path = db_path or DB_PATH

    def table_exists(self, table_name: str) -> bool:
        with get_connection(self.db_path) as con:
            row = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
                (table_name,),
            ).fetchone()
        return row is not None

    def matched_trades(self, date_prefix: str | None = None) -> list[dict[str, Any]]:
        if not self.table_exists("matched_trades"):
            return []

        where = ""
        params: list[Any] = []

        if date_prefix:
            where = "WHERE exit_timestamp LIKE ?"
            params.append(f"{date_prefix}%")

        with get_connection(self.db_path) as con:
            rows = con.execute(
                f"""
                SELECT *
                FROM matched_trades
                {where}
                ORDER BY exit_timestamp ASC
                """,
                params,
            ).fetchall()

        return [dict(row) for row in rows]

    def trade_rows(
        self,
        date_prefix: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        where = "WHERE 1=1"
        params: list[Any] = []

        if date_prefix:
            where += " AND timestamp LIKE ?"
            params.append(f"{date_prefix}%")

        limit_sql = ""
        if limit:
            limit_sql = " LIMIT ?"
            params.append(int(limit))

        with get_connection(self.db_path) as con:
            rows = con.execute(
                f"""
                SELECT *
                FROM trades
                {where}
                ORDER BY id ASC
                {limit_sql}
                """,
                params,
            ).fetchall()

        return [dict(row) for row in rows]
