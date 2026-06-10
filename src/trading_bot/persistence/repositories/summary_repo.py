"""Repository reads for daily and weekly summary reports."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection

TRADE_CONTEXT_COLUMNS = """
    id,
    timestamp,
    symbol,
    action,
    approved,
    rejection_reason,
    confidence,
    setup_label,
    setup_policy_action,
    setup_policy_reason
"""


class SummaryRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def trades_for_day(self, target_date: str) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as con:
            rows = con.execute(
                "SELECT * FROM trades WHERE timestamp LIKE ?",
                (f"{target_date}%",),
            ).fetchall()
        return [dict(row) for row in rows]

    def trades_for_range(self, start_date: str, end_date: str) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT *
                FROM trades
                WHERE timestamp >= ? AND timestamp < ?
                """,
                (start_date, end_date),
            ).fetchall()
        return [dict(row) for row in rows]

    def trade_context_rows_for_day(self, target_date: str) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as con:
            rows = con.execute(
                f"""
                SELECT {TRADE_CONTEXT_COLUMNS}
                FROM trades
                WHERE timestamp LIKE ?
                ORDER BY timestamp ASC
                """,
                (f"{target_date}%",),
            ).fetchall()
        return [dict(row) for row in rows]

    def trade_context_rows_for_range(
        self,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as con:
            rows = con.execute(
                f"""
                SELECT {TRADE_CONTEXT_COLUMNS}
                FROM trades
                WHERE timestamp >= ? AND timestamp < ?
                ORDER BY timestamp ASC
                """,
                (start_date, end_date),
            ).fetchall()
        return [dict(row) for row in rows]

    def matched_trades_for_day(self, target_date: str) -> list[dict[str, Any]]:
        return self._matched_trades(
            "AND exit_timestamp LIKE ?",
            (f"{target_date}%",),
        )

    def matched_trades_for_range(
        self,
        start_date: str,
        end_date: str,
    ) -> list[dict[str, Any]]:
        return self._matched_trades(
            "AND exit_timestamp >= ? AND exit_timestamp < ?",
            (start_date, end_date),
        )

    def _matched_trades(self, extra_where: str, params) -> list[dict[str, Any]]:
        try:
            with get_connection(self.db_path) as con:
                rows = con.execute(
                    f"""
                    SELECT symbol, qty, entry_price, exit_price, realized_pnl, won
                    FROM matched_trades
                    WHERE 1=1 {extra_where}
                    ORDER BY exit_timestamp ASC
                    """,
                    params,
                ).fetchall()
        except sqlite3.OperationalError:
            return []

        return [dict(row) for row in rows]
