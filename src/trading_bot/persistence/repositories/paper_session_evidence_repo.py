"""Repository reads for paper-session evidence diagnostics."""

from __future__ import annotations

import json
import sqlite3
from pathlib import Path
from typing import Any


class PaperSessionEvidenceRepository:
    def __init__(self, db_path: Path | str):
        self.db_path = Path(db_path)

    def exists(self) -> bool:
        return self.db_path.exists()

    def count(
        self,
        table: str,
        *,
        date_column: str,
        target_date: str,
        extra_where: str = "",
    ) -> int:
        with self._connect() as con:
            if not self.table_exists(table, con=con):
                return 0
            if date_column not in self.columns(table, con=con):
                return 0
            where = f"substr({date_column}, 1, 10) = ?"
            if extra_where:
                where += f" AND {extra_where}"
            row = con.execute(
                f"SELECT COUNT(*) AS n FROM {table} WHERE {where}",
                (target_date,),
            ).fetchone()
        return int(row["n"] or 0) if row else 0

    def candidate_rows(self, target_date: str) -> list[dict[str, Any]]:
        with self._connect() as con:
            if not self.table_exists("candidate_universe", con=con):
                return []
            rows = con.execute(
                """
                SELECT *
                FROM candidate_universe
                WHERE substr(candidate_ts, 1, 10) = ?
                ORDER BY candidate_ts ASC, id ASC
                """,
                (target_date,),
            ).fetchall()
        return [dict(row) for row in rows]

    def decision_policy_learning_effect_rows(self, target_date: str) -> int:
        with self._connect() as con:
            if not self.table_exists("decision_snapshots", con=con):
                return 0
            columns = self.columns("decision_snapshots", con=con)
            if "canonical_intelligence_json" not in columns and "account_state_json" not in columns:
                return 0
            select_cols = [
                col
                for col in ("canonical_intelligence_json", "account_state_json")
                if col in columns
            ]
            rows = con.execute(
                f"""
                SELECT {", ".join(select_cols)}
                FROM decision_snapshots
                WHERE substr(decision_time, 1, 10) = ?
                """,
                (target_date,),
            ).fetchall()

        count = 0
        for row in rows:
            for col in select_cols:
                payload = self._load_json(row[col])
                outcome = self._path(
                    payload,
                    "advisory_authority_state",
                    "decision_policy_outcome",
                ) or payload.get("decision_policy_outcome")
                if isinstance(outcome, dict) and (
                    outcome.get("advisory_decision")
                    or outcome.get("effect_on_execution")
                    or outcome.get("effect_on_size")
                ):
                    count += 1
                    break
        return count

    def has_column(self, table: str, column: str) -> bool:
        with self._connect() as con:
            return column in self.columns(table, con=con)

    def table_exists(self, table: str, *, con: sqlite3.Connection | None = None) -> bool:
        if con is None:
            with self._connect() as owned:
                return self.table_exists(table, con=owned)
        row = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None

    def columns(self, table: str, *, con: sqlite3.Connection | None = None) -> set[str]:
        if con is None:
            with self._connect() as owned:
                return self.columns(table, con=owned)
        if not self.table_exists(table, con=con):
            return set()
        return {str(row["name"]) for row in con.execute(f"PRAGMA table_info({table})").fetchall()}

    def _connect(self) -> sqlite3.Connection:
        con = sqlite3.connect(self.db_path)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _load_json(raw: Any) -> dict[str, Any]:
        if isinstance(raw, dict):
            return raw
        if not raw:
            return {}
        try:
            loaded = json.loads(str(raw))
            return loaded if isinstance(loaded, dict) else {}
        except Exception:
            return {}

    @staticmethod
    def _path(payload: dict[str, Any], *keys: str) -> Any:
        current: Any = payload
        for key in keys:
            if not isinstance(current, dict):
                return None
            current = current.get(key)
        return current
