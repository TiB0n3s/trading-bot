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
                    decision_snapshot_id INTEGER,
                    entry_trade_id INTEGER,
                    exit_trade_id INTEGER,
                    matched_trade_id INTEGER,
                    position_id TEXT,
                    symbol TEXT,
                    exit_timestamp TEXT,
                    exit_trigger TEXT,
                    exit_source TEXT,
                    realized_pnl REAL,
                    realized_return_pct REAL,
                    mfe_pct REAL,
                    capture_ratio REAL,
                    max_adverse_excursion_pct REAL,
                    avoided_drawdown_pct REAL,
                    missed_upside_pct REAL,
                    post_exit_return_30m_pct REAL,
                    post_exit_return_60m_pct REAL,
                    reentry_window_summary TEXT,
                    exit_regime_state_json TEXT,
                    exit_momentum_state_json TEXT,
                    exit_trend_state_json TEXT,
                    canonical_exit_version TEXT NOT NULL,
                    canonical_exit_hash TEXT NOT NULL,
                    canonical_exit_json TEXT NOT NULL,
                    canonical_intelligence_hash TEXT,
                    entry_canonical_intelligence_version TEXT,
                    entry_canonical_intelligence_hash TEXT
                )
                """
            )
            existing_cols = {
                row["name"]
                for row in con.execute("PRAGMA table_info(exit_snapshots)").fetchall()
            }
            addable = {
                "decision_snapshot_id": "INTEGER",
                "entry_trade_id": "INTEGER",
                "position_id": "TEXT",
                "max_adverse_excursion_pct": "REAL",
                "reentry_window_summary": "TEXT",
                "exit_regime_state_json": "TEXT",
                "exit_momentum_state_json": "TEXT",
                "exit_trend_state_json": "TEXT",
                "entry_canonical_intelligence_version": "TEXT",
                "entry_canonical_intelligence_hash": "TEXT",
            }
            for col, col_type in addable.items():
                if col not in existing_cols:
                    con.execute(f"ALTER TABLE exit_snapshots ADD COLUMN {col} {col_type}")
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
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_exit_snapshots_decision
                ON exit_snapshots(decision_snapshot_id)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_exit_snapshots_entry_hash
                ON exit_snapshots(entry_canonical_intelligence_hash)
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
