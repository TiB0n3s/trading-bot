"""Repository boundary for event_attribution_report.py reads."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class EventAttributionReportRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def events(
        self,
        target_date: str,
        symbol: str | None = None,
        event_type: str | None = None,
    ) -> list[Any]:
        params: list[Any] = [target_date]
        filters = ["market_date = ?"]

        if symbol:
            filters.append("symbol = ?")
            params.append(symbol.upper())

        if event_type:
            filters.append("event_type = ?")
            params.append(event_type)

        where = " AND ".join(filters)

        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT *
                FROM daily_symbol_events
                WHERE {where}
                ORDER BY symbol, event_type, id
                """,
                params,
            ).fetchall()

    def context_by_symbol(self, target_date: str) -> dict[str, Any]:
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT *
                FROM daily_symbol_context
                WHERE market_date = ?
                """,
                (target_date,),
            ).fetchall()
        return {row["symbol"]: row for row in rows}

    def trade_rows(self, target_date: str, symbol: str) -> list[Any]:
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT *
                FROM trades
                WHERE timestamp LIKE ?
                  AND symbol = ?
                ORDER BY timestamp ASC, id ASC
                """,
                (f"{target_date}%", symbol),
            ).fetchall()

    def matched_rows(self, target_date: str, symbol: str) -> list[Any]:
        try:
            with get_connection(self.db_path) as con:
                return con.execute(
                    """
                    SELECT *
                    FROM matched_trades
                    WHERE exit_timestamp LIKE ?
                      AND symbol = ?
                    ORDER BY exit_timestamp ASC
                    """,
                    (f"{target_date}%", symbol),
                ).fetchall()
        except Exception:
            return []
