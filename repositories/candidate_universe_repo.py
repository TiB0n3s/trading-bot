"""Repository boundary for canonical candidate-universe persistence."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class CandidateUniverseRepository:
    """Persist scored candidates before final thresholding.

    This table is intentionally broader than auto-buy candidates. It can hold
    entry candidates, near-threshold candidates, and exit candidates considered
    but not taken so downstream training is less biased toward acted-on paths.
    """

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = db_path or DB_PATH

    def init_table(self) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS candidate_universe (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    candidate_ts TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    candidate_kind TEXT NOT NULL,
                    candidate_status TEXT NOT NULL,
                    score REAL,
                    threshold REAL,
                    threshold_distance REAL,
                    decision TEXT,
                    reason TEXT,
                    source TEXT,
                    setup_label TEXT,
                    regime TEXT,
                    session_phase TEXT,
                    canonical_intelligence_hash TEXT,
                    canonical_intelligence_version TEXT,
                    candidate_json TEXT NOT NULL,
                    runtime_effect TEXT NOT NULL DEFAULT 'candidate_capture_only_no_live_authority'
                )
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_candidate_universe_time
                ON candidate_universe(candidate_ts)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_candidate_universe_symbol_time
                ON candidate_universe(symbol, candidate_ts)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_candidate_universe_kind_status
                ON candidate_universe(candidate_kind, candidate_status)
                """
            )

    def insert_candidate(self, row: dict[str, Any]) -> int:
        self.init_table()
        columns = list(row.keys())
        placeholders = ", ".join(["?"] * len(columns))
        with get_connection(self.db_path) as con:
            cur = con.execute(
                f"""
                INSERT INTO candidate_universe ({', '.join(columns)})
                VALUES ({placeholders})
                """,
                [row[col] for col in columns],
            )
            return int(cur.lastrowid)

    def rows_for_date(
        self,
        target_date: str,
        *,
        symbol: str | None = None,
        candidate_kind: str | None = None,
    ) -> list[Any]:
        self.init_table()
        clauses = ["substr(candidate_ts, 1, 10) = ?"]
        params: list[Any] = [target_date]
        if symbol:
            clauses.append("UPPER(symbol) = ?")
            params.append(symbol.upper())
        if candidate_kind:
            clauses.append("candidate_kind = ?")
            params.append(candidate_kind)
        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT *
                FROM candidate_universe
                WHERE {' AND '.join(clauses)}
                ORDER BY candidate_ts ASC, id ASC
                """,
                params,
            ).fetchall()

    def rows_between(
        self,
        start_date: str,
        end_date: str,
        *,
        symbol: str | None = None,
        candidate_kind: str | None = None,
    ) -> list[Any]:
        self.init_table()
        clauses = ["substr(candidate_ts, 1, 10) BETWEEN ? AND ?"]
        params: list[Any] = [start_date, end_date]
        if symbol:
            clauses.append("UPPER(symbol) = ?")
            params.append(symbol.upper())
        if candidate_kind:
            clauses.append("candidate_kind = ?")
            params.append(candidate_kind)
        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT *
                FROM candidate_universe
                WHERE {' AND '.join(clauses)}
                ORDER BY candidate_ts ASC, id ASC
                """,
                params,
            ).fetchall()
