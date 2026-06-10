"""Repository boundary for context_trade_join_report.py reads."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class ContextTradeJoinRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def context_rows(
        self,
        start_date: str | None,
        end_date: str | None,
        symbol: str | None = None,
    ) -> list[Any]:
        params: list[Any] = []
        where = ["1=1"]

        if start_date:
            where.append("market_date >= ?")
            params.append(start_date)
        if end_date:
            where.append("market_date < ?")
            params.append(end_date)
        if symbol:
            where.append("symbol = ?")
            params.append(symbol.upper())

        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT *
                FROM daily_symbol_context
                WHERE {" AND ".join(where)}
                ORDER BY market_date, symbol
                """,
                params,
            ).fetchall()

    def trade_rows(self, market_date: str, symbol: str) -> list[Any]:
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT *
                FROM trades
                WHERE timestamp LIKE ?
                  AND symbol = ?
                ORDER BY timestamp ASC, id ASC
                """,
                (f"{market_date}%", symbol),
            ).fetchall()

    def matched_rows(self, market_date: str, symbol: str) -> list[Any]:
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
                    (f"{market_date}%", symbol),
                ).fetchall()
        except Exception:
            return []
