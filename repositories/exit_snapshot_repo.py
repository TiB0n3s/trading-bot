"""Repository boundary for canonical exit snapshots."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class ExitSnapshotRepository:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = db_path or DB_PATH

    def init_table(self) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS exit_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    exit_trade_id INTEGER,
                    matched_trade_id INTEGER,
                    symbol TEXT,
                    exit_timestamp TEXT,
                    exit_trigger TEXT,
                    exit_source TEXT,
                    realized_pnl REAL,
                    realized_return_pct REAL,
                    mfe_pct REAL,
                    capture_ratio REAL,
                    avoided_drawdown_pct REAL,
                    missed_upside_pct REAL,
                    post_exit_return_30m_pct REAL,
                    post_exit_return_60m_pct REAL,
                    canonical_exit_version TEXT NOT NULL,
                    canonical_exit_hash TEXT NOT NULL,
                    canonical_exit_json TEXT NOT NULL,
                    canonical_intelligence_hash TEXT
                )
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_exit_snapshots_symbol_time
                ON exit_snapshots(symbol, exit_timestamp)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_exit_snapshots_trade
                ON exit_snapshots(exit_trade_id, matched_trade_id)
                """
            )

    def insert_snapshot(self, row: dict[str, Any]) -> int:
        self.init_table()
        columns = list(row.keys())
        placeholders = ", ".join(["?"] * len(columns))
        with get_connection(self.db_path) as con:
            cur = con.execute(
                f"INSERT INTO exit_snapshots ({', '.join(columns)}) VALUES ({placeholders})",
                [row[col] for col in columns],
            )
            return int(cur.lastrowid)

    def latest_for_symbol(self, symbol: str, limit: int = 20):
        self.init_table()
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT *
                FROM exit_snapshots
                WHERE symbol = ?
                ORDER BY exit_timestamp DESC, id DESC
                LIMIT ?
                """,
                (symbol, limit),
            ).fetchall()
