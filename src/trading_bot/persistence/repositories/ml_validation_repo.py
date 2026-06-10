"""Repository boundary for ML validation dataset probes."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from db import DB_PATH


class MLValidationRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)

    def _connect(self):
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _table_exists(con: sqlite3.Connection, table: str) -> bool:
        row = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    def feature_snapshots_exists(self) -> bool:
        if not self.db_path.exists():
            return False
        with self._connect() as con:
            return self._table_exists(con, "feature_snapshots")

    def feature_snapshot_columns(self) -> set[str]:
        if not self.db_path.exists():
            return set()
        with self._connect() as con:
            if not self._table_exists(con, "feature_snapshots"):
                return set()
            return {
                row[1] for row in con.execute("PRAGMA table_info(feature_snapshots)").fetchall()
            }

    def count_feature_snapshots_between(self, start: str | None, end: str | None) -> int:
        if not start or not end or not self.db_path.exists():
            return 0
        with self._connect() as con:
            if not self._table_exists(con, "feature_snapshots"):
                return 0
            row = con.execute(
                """
                SELECT COUNT(*)
                FROM feature_snapshots
                WHERE substr(timestamp,1,10) BETWEEN ? AND ?
                """,
                (start, end),
            ).fetchone()
        return int(row[0] or 0)

    def distinct_symbols_between(self, start: str | None, end: str | None) -> set[str]:
        if not start or not end or not self.db_path.exists():
            return set()
        with self._connect() as con:
            if not self._table_exists(con, "feature_snapshots"):
                return set()
            rows = con.execute(
                """
                SELECT DISTINCT symbol
                FROM feature_snapshots
                WHERE substr(timestamp,1,10) BETWEEN ? AND ?
                """,
                (start, end),
            ).fetchall()
        return {row[0] for row in rows}

    def count_feature_snapshots_for_symbols_between(
        self,
        symbols: list[str],
        start: str,
        end: str,
    ) -> int:
        if not symbols or not self.db_path.exists():
            return 0
        placeholders = ",".join("?" * len(symbols))
        with self._connect() as con:
            if not self._table_exists(con, "feature_snapshots"):
                return 0
            row = con.execute(
                f"""
                SELECT COUNT(*)
                FROM feature_snapshots
                WHERE symbol IN ({placeholders})
                  AND substr(timestamp,1,10) BETWEEN ? AND ?
                """,
                symbols + [start, end],
            ).fetchone()
        return int(row[0] or 0)

    def complete_label_rows_between(self, start: str, end: str) -> int:
        if not self.db_path.exists():
            return 0
        with self._connect() as con:
            if not (
                self._table_exists(con, "feature_snapshots")
                and self._table_exists(con, "labeled_setups")
            ):
                return 0
            row = con.execute(
                """
                SELECT COUNT(*)
                FROM feature_snapshots fs
                JOIN labeled_setups ls ON ls.snapshot_id = fs.id
                WHERE substr(fs.timestamp,1,10) BETWEEN ? AND ?
                  AND ls.ret_fwd_5m IS NOT NULL
                  AND ls.ret_fwd_15m IS NOT NULL
                  AND ls.ret_fwd_30m IS NOT NULL
                """,
                (start, end),
            ).fetchone()
        return int(row[0] or 0)

    def feature_available_at_violations_between(self, start: str, end: str) -> int:
        if "feature_available_at" not in self.feature_snapshot_columns():
            return 0
        with self._connect() as con:
            row = con.execute(
                """
                SELECT COUNT(*)
                FROM feature_snapshots
                WHERE substr(timestamp,1,10) BETWEEN ? AND ?
                  AND substr(feature_available_at,1,10) > substr(timestamp,1,10)
                """,
                (start, end),
            ).fetchone()
        return int(row[0] or 0)

    def stale_feature_rows_between(self, start: str, end: str) -> int:
        if "is_stale" not in self.feature_snapshot_columns():
            return 0
        with self._connect() as con:
            row = con.execute(
                """
                SELECT COUNT(*)
                FROM feature_snapshots
                WHERE substr(timestamp,1,10) BETWEEN ? AND ?
                  AND is_stale = 1
                """,
                (start, end),
            ).fetchone()
        return int(row[0] or 0)

    def last_train_dates_for_symbols_between(
        self,
        symbols: list[str],
        start: str,
        end: str,
    ) -> list[dict[str, Any]]:
        if not symbols or not self.db_path.exists():
            return []
        placeholders = ",".join("?" * len(symbols))
        with self._connect() as con:
            if not self._table_exists(con, "feature_snapshots"):
                return []
            rows = con.execute(
                f"""
                SELECT symbol, MAX(substr(timestamp,1,10)) AS last_date
                FROM feature_snapshots
                WHERE symbol IN ({placeholders})
                  AND substr(timestamp,1,10) BETWEEN ? AND ?
                GROUP BY symbol
                """,
                symbols + [start, end],
            ).fetchall()
        return [dict(row) for row in rows]

    def first_test_dates_for_symbols_between(
        self,
        symbols: list[str],
        start: str,
        end: str,
    ) -> dict[str, str]:
        if not symbols or not self.db_path.exists():
            return {}
        placeholders = ",".join("?" * len(symbols))
        with self._connect() as con:
            if not self._table_exists(con, "feature_snapshots"):
                return {}
            rows = con.execute(
                f"""
                SELECT symbol, MIN(substr(timestamp,1,10)) AS first_date
                FROM feature_snapshots
                WHERE symbol IN ({placeholders})
                  AND substr(timestamp,1,10) BETWEEN ? AND ?
                GROUP BY symbol
                """,
                symbols + [start, end],
            ).fetchall()
        return {row[0]: row[1] for row in rows}
