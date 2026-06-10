"""Repository reads for excursion analysis reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class ExcursionRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def load_matched_trades(
        self,
        target_date: str | None = None,
        symbol: str | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        params: list[Any] = []
        extra = ""

        if target_date:
            extra += " AND exit_timestamp LIKE ?"
            params.append(f"{target_date}%")

        if symbol:
            extra += " AND symbol = ?"
            params.append(symbol.upper())

        params.append(limit)

        with get_connection(self.db_path) as con:
            rows = con.execute(
                f"""
                SELECT *
                FROM matched_trades
                WHERE 1=1
                  {extra}
                ORDER BY exit_timestamp DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

        return [dict(row) for row in rows]
