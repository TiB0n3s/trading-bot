"""Repository boundary for bot event audit rows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class BotEventsRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def init_table(self) -> None:
        with get_connection(self.db_path) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS bot_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    symbol TEXT,
                    action TEXT,
                    decision TEXT,
                    severity TEXT,
                    reason TEXT,
                    source TEXT,
                    payload_json TEXT
                )
            """)

            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_bot_events_timestamp
                ON bot_events(timestamp)
            """)

            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_bot_events_type_symbol
                ON bot_events(event_type, symbol)
            """)

    def insert_event(self, event: dict[str, Any]) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                INSERT INTO bot_events (
                    timestamp,
                    event_type,
                    symbol,
                    action,
                    decision,
                    severity,
                    reason,
                    source,
                    payload_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    event.get("timestamp"),
                    event.get("event_type"),
                    event.get("symbol"),
                    event.get("action"),
                    event.get("decision"),
                    event.get("severity"),
                    event.get("reason"),
                    event.get("source"),
                    event.get("payload_json"),
                ),
            )

    def fetch_events(
        self,
        *,
        limit: int = 50,
        event_type: str | None = None,
        symbol: str | None = None,
        since: str | None = None,
    ):
        params: list[Any] = []
        where = ["1=1"]

        if event_type:
            where.append("event_type = ?")
            params.append(event_type)

        if symbol:
            where.append("symbol = ?")
            params.append(symbol.upper())

        if since:
            where.append("timestamp >= ?")
            params.append(since)

        params.append(limit)

        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT
                    id,
                    timestamp,
                    event_type,
                    symbol,
                    action,
                    decision,
                    severity,
                    reason,
                    source,
                    payload_json
                FROM bot_events
                WHERE {" AND ".join(where)}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
