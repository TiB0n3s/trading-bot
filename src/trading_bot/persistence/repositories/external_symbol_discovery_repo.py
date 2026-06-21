"""Repository reads for external-symbol discovery event context."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from db import DB_PATH, get_read_connection


class ExternalSymbolDiscoveryRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)

    def exists(self) -> bool:
        return self.db_path.exists()

    def _connect(self) -> sqlite3.Connection:
        return get_read_connection(self.db_path)

    @staticmethod
    def _table_exists(con: sqlite3.Connection, table: str) -> bool:
        return bool(
            con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
                (table,),
            ).fetchone()
        )

    @staticmethod
    def _table_columns(con: sqlite3.Connection, table: str) -> set[str]:
        return {str(row["name"]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}

    def daily_symbol_event_rows(
        self,
        *,
        start_date: str,
        end_date: str,
    ) -> dict[str, Any]:
        if not self.exists():
            return {
                "status": "missing_db",
                "db_path": str(self.db_path),
                "rows": [],
            }

        with self._connect() as con:
            if not self._table_exists(con, "daily_symbol_events"):
                return {
                    "status": "missing_table",
                    "rows": [],
                }

            columns = self._table_columns(con, "daily_symbol_events")
            optional = {
                "id": "id",
                "market_date": "market_date",
                "symbol": "symbol",
                "event_type": "event_type",
                "event_subtype": "event_subtype",
                "event_summary": "event_summary",
                "expected_market_impact": "expected_market_impact",
                "trade_relevance": "trade_relevance",
                "confidence": "confidence",
                "source": "source",
                "source_url": "source_url",
                "raw_json": "raw_json",
                "created_at": "created_at",
            }
            select_parts = [
                column if column in columns else f"NULL AS {alias}"
                for alias, column in optional.items()
            ]
            order_expr = (
                "created_at ASC, id ASC"
                if "created_at" in columns and "id" in columns
                else "market_date ASC"
            )
            rows = [
                dict(row)
                for row in con.execute(
                    f"""
                    SELECT {", ".join(select_parts)}
                    FROM daily_symbol_events
                    WHERE market_date >= ?
                      AND market_date <= ?
                    ORDER BY {order_expr}
                    """,
                    (start_date, end_date),
                ).fetchall()
            ]

        return {
            "status": "ok",
            "rows": rows,
        }
