from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class SignalOutcomeRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def init_table(self) -> None:
        with get_connection(self.db_path) as con:
            con.execute("""
                CREATE TABLE IF NOT EXISTS historical_signal_outcomes (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,

                    signal_id INTEGER NOT NULL,
                    market_date TEXT,
                    symbol TEXT,
                    action TEXT,
                    signal_timestamp TEXT,
                    signal_price REAL,
                    approved INTEGER,
                    decision_summary TEXT,
                    rejection_reason TEXT,

                    matched_outcome_id INTEGER,
                    outcome_source TEXT,
                    entry_timestamp TEXT,
                    exit_timestamp TEXT,
                    entry_delay_minutes REAL,
                    exit_delay_minutes REAL,
                    holding_minutes REAL,
                    qty REAL,
                    entry_price REAL,
                    exit_price REAL,
                    realized_pnl REAL,
                    realized_pnl_pct REAL,
                    exit_type TEXT,

                    signal_to_entry_pct REAL,
                    signal_to_exit_pct REAL,
                    entry_timing_label TEXT,
                    exit_timing_label TEXT,
                    learning_label TEXT,
                    learning_reason TEXT,

                    created_at TEXT NOT NULL,

                    UNIQUE(signal_id)
                )
            """)
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_historical_signal_outcomes_date_symbol
                ON historical_signal_outcomes(market_date, symbol)
            """)
            con.execute("""
                CREATE INDEX IF NOT EXISTS idx_historical_signal_outcomes_labels
                ON historical_signal_outcomes(entry_timing_label, exit_timing_label, learning_label)
            """)

    def load_signal_events(self, where: list[str], params: list[Any]) -> list[Any]:
        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT
                    id,
                    first_timestamp AS timestamp,
                    market_date,
                    symbol,
                    action,
                    signal_price,
                    approved,
                    order_id,
                    rejection_reason,
                    decision_summary
                FROM historical_signal_events
                WHERE {' AND '.join(where)}
                ORDER BY first_timestamp, id
                """,
                params,
            ).fetchall()

    def load_signal_experience(self, where: list[str], params: list[Any]) -> list[Any]:
        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT *
                FROM historical_signal_experience
                WHERE {' AND '.join(where)}
                ORDER BY timestamp, id
                """,
                params,
            ).fetchall()

    def load_trade_outcomes(self) -> list[Any]:
        with get_connection(self.db_path) as con:
            return con.execute("""
                SELECT *
                FROM historical_trade_outcomes
                ORDER BY entry_timestamp, exit_timestamp, id
            """).fetchall()

    def insert_signal_outcome_rows(self, rows: list[dict[str, Any]], *, replace: bool = False) -> int:
        now = datetime.now().isoformat(sep=" ", timespec="seconds")
        inserted = 0
        with get_connection(self.db_path) as con:
            if replace:
                con.execute("DELETE FROM historical_signal_outcomes")

            for r in rows:
                cur = con.execute(
                    """
                    INSERT OR REPLACE INTO historical_signal_outcomes (
                        signal_id, market_date, symbol, action, signal_timestamp,
                        signal_price, approved, decision_summary, rejection_reason,

                        matched_outcome_id, outcome_source, entry_timestamp, exit_timestamp,
                        entry_delay_minutes, exit_delay_minutes, holding_minutes, qty,
                        entry_price, exit_price, realized_pnl, realized_pnl_pct, exit_type,

                        signal_to_entry_pct, signal_to_exit_pct, entry_timing_label,
                        exit_timing_label, learning_label, learning_reason, created_at
                    )
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        r["signal_id"],
                        r["market_date"],
                        r["symbol"],
                        r["action"],
                        r["signal_timestamp"],
                        r["signal_price"],
                        r["approved"],
                        r["decision_summary"],
                        r["rejection_reason"],
                        r["matched_outcome_id"],
                        r["outcome_source"],
                        r["entry_timestamp"],
                        r["exit_timestamp"],
                        r["entry_delay_minutes"],
                        r["exit_delay_minutes"],
                        r["holding_minutes"],
                        r["qty"],
                        r["entry_price"],
                        r["exit_price"],
                        r["realized_pnl"],
                        r["realized_pnl_pct"],
                        r["exit_type"],
                        r["signal_to_entry_pct"],
                        r["signal_to_exit_pct"],
                        r["entry_timing_label"],
                        r["exit_timing_label"],
                        r["learning_label"],
                        r["learning_reason"],
                        now,
                    ),
                )
                inserted += cur.rowcount
        return inserted
