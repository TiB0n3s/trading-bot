"""Read-only repository for ledger table introspection and summaries."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class LedgerRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def table_exists(self, table_name: str) -> bool:
        with get_connection(self.db_path) as con:
            row = con.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
                (table_name,),
            ).fetchone()

        return row is not None

    def table_columns(self, table_name: str) -> list[str]:
        if not self.table_exists(table_name):
            return []

        with get_connection(self.db_path) as con:
            rows = con.execute(f"PRAGMA table_info({table_name})").fetchall()

        return [r["name"] for r in rows]

    def trades_columns(self) -> list[str]:
        return self.table_columns("trades")

    def count_rows(self, table_name: str) -> int:
        if not self.table_exists(table_name):
            return 0

        with get_connection(self.db_path) as con:
            row = con.execute(f"SELECT COUNT(*) AS n FROM {table_name}").fetchone()

        return int(row["n"] or 0)

    def latest_trade_rows(self, limit: int = 10) -> list[dict[str, Any]]:
        limit = max(1, min(int(limit), 100))

        if not self.table_exists("trades"):
            return []

        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT *
                FROM trades
                ORDER BY id DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()

        return [dict(r) for r in rows]

    def ledger_summary(self) -> dict[str, Any]:
        return {
            "db_path": str(self.db_path),
            "has_trades": self.table_exists("trades"),
            "has_matched_trades": self.table_exists("matched_trades"),
            "has_fill_events": self.table_exists("fill_events"),
            "trades_count": self.count_rows("trades"),
            "matched_trades_count": self.count_rows("matched_trades"),
            "fill_events_count": self.count_rows("fill_events"),
            "trades_columns": self.trades_columns(),
        }
