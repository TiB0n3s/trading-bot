"""Repository boundary for immutable decision snapshots."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, ensure_decision_snapshots_table, get_connection


class DecisionSnapshotRepository:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = db_path or DB_PATH

    def ensure_table(self) -> None:
        ensure_decision_snapshots_table(self.db_path)

    def insert_snapshot(self, row: dict[str, Any]) -> int:
        self.ensure_table()
        columns = list(row.keys())
        placeholders = ", ".join(["?"] * len(columns))
        with get_connection(self.db_path) as con:
            cur = con.execute(
                f"INSERT INTO decision_snapshots ({', '.join(columns)}) VALUES ({placeholders})",
                [row[col] for col in columns],
            )
            return int(cur.lastrowid)

    def summarize_snapshots(self, target_date: str) -> dict[str, Any]:
        self.ensure_table()
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT final_decision, approved, COUNT(*) AS n
                FROM decision_snapshots
                WHERE substr(decision_time, 1, 10) = ?
                GROUP BY final_decision, approved
                ORDER BY n DESC, final_decision
                """,
                (target_date,),
            ).fetchall()
            total = con.execute(
                """
                SELECT COUNT(*) AS n,
                       COUNT(DISTINCT symbol) AS symbols,
                       SUM(CASE WHEN market_context_hash IS NULL THEN 1 ELSE 0 END) AS missing_context_hash,
                       SUM(CASE WHEN git_sha IS NULL THEN 1 ELSE 0 END) AS missing_git_sha
                FROM decision_snapshots
                WHERE substr(decision_time, 1, 10) = ?
                """,
                (target_date,),
            ).fetchone()

        return {
            "total": int(total["n"] or 0),
            "symbols": int(total["symbols"] or 0),
            "missing_context_hash": int(total["missing_context_hash"] or 0),
            "missing_git_sha": int(total["missing_git_sha"] or 0),
            "by_decision": [dict(row) for row in rows],
        }

    def table_exists(self, table_name: str) -> bool:
        with get_connection(self.db_path) as con:
            row = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            ).fetchone()
        return row is not None

    def trade_count_for_date(self, target_date: str) -> int:
        with get_connection(self.db_path) as con:
            row = con.execute(
                "SELECT COUNT(*) AS n FROM trades WHERE substr(timestamp, 1, 10) = ?",
                (target_date,),
            ).fetchone()
        return int(row["n"] or 0) if row else 0

    def snapshot_trade_count_for_date(self, target_date: str) -> int:
        with get_connection(self.db_path) as con:
            row = con.execute(
                """
                SELECT COUNT(DISTINCT trade_id) AS n
                FROM decision_snapshots
                WHERE substr(decision_time, 1, 10) = ?
                  AND trade_id IS NOT NULL
                """,
                (target_date,),
            ).fetchone()
        return int(row["n"] or 0) if row else 0
