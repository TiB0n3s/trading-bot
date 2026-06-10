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

    def list_trace_rows(self, target_date: str, limit: int = 500) -> list[dict[str, Any]]:
        if not Path(self.db_path).exists() or not self.table_exists("decision_snapshots"):
            return []
        with get_connection(self.db_path) as con:
            columns = {
                row["name"]
                for row in con.execute("PRAGMA table_info(decision_snapshots)").fetchall()
            }
            gate_trace_expr = (
                "gate_trace_json" if "gate_trace_json" in columns else "NULL AS gate_trace_json"
            )
            try:
                rows = con.execute(
                    f"""
                    SELECT id, decision_time, symbol, action, final_decision,
                           rejection_reason, {gate_trace_expr}, account_state_json
                      FROM decision_snapshots
                     WHERE substr(decision_time, 1, 10) = ?
                       AND account_state_json IS NOT NULL
                     ORDER BY decision_time DESC
                     LIMIT ?
                    """,
                    (target_date, int(limit)),
                ).fetchall()
            except Exception:
                return []
        return [dict(row) for row in rows]

    def list_canonical_repair_rows(self, target_date: str) -> list[dict[str, Any]]:
        if not Path(self.db_path).exists() or not self.table_exists("decision_snapshots"):
            return []
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT id, canonical_intelligence_json, account_state_json
                FROM decision_snapshots
                WHERE substr(decision_time, 1, 10) = ?
                ORDER BY decision_time ASC, id ASC
                """,
                (target_date,),
            ).fetchall()
        return [dict(row) for row in rows]

    def update_canonical_intelligence_many(
        self,
        updates: list[tuple[str, str, str, int]],
    ) -> None:
        if not updates:
            return
        self.ensure_table()
        with get_connection(self.db_path) as con:
            con.executemany(
                """
                UPDATE decision_snapshots
                SET canonical_intelligence_version = ?,
                    canonical_intelligence_hash = ?,
                    canonical_intelligence_json = ?
                WHERE id = ?
                """,
                updates,
            )
