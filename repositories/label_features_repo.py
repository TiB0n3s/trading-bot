from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class LabelFeaturesRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def table_exists(self, table_name: str) -> bool:
        with get_connection(self.db_path) as con:
            row = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            ).fetchone()
        return row is not None

    def table_columns(self, table_name: str) -> set[str]:
        with get_connection(self.db_path) as con:
            rows = con.execute(f"PRAGMA table_info({table_name})").fetchall()
        return {row["name"] for row in rows}

    def label_summary(self):
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT COUNT(*) AS n, MIN(timestamp) AS min_ts, MAX(timestamp) AS max_ts
                FROM labeled_setups
                """
            ).fetchone()

    def session_label_summary(self, target_date: str):
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT COUNT(*) AS n,
                       MIN(timestamp) AS first_ts,
                       MAX(timestamp) AS last_ts,
                       COUNT(DISTINCT symbol) AS symbols_seen
                FROM labeled_setups
                WHERE substr(timestamp, 1, 10) = ?
                """,
                (target_date,),
            ).fetchone()

    def outcome_rows(self, target_date: str):
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT COALESCE(outcome_label, 'missing') AS outcome_label, COUNT(*) AS n
                FROM labeled_setups
                WHERE substr(timestamp, 1, 10) = ?
                GROUP BY COALESCE(outcome_label, 'missing')
                ORDER BY outcome_label
                """,
                (target_date,),
            ).fetchall()

    def unlabeled_snapshots(self, cutoff: datetime, limit: int) -> list[Any]:
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT fs.id, fs.symbol, fs.timestamp, fs.last_price
                FROM feature_snapshots fs
                LEFT JOIN labeled_setups ls
                  ON ls.snapshot_id = fs.id
                WHERE ls.snapshot_id IS NULL
                  AND fs.last_price IS NOT NULL
                  AND fs.timestamp <= ?
                ORDER BY fs.timestamp ASC
                LIMIT ?
                """,
                (cutoff.isoformat(), limit),
            ).fetchall()

    def insert_label(
        self,
        row: Any,
        *,
        fwd5: float | None,
        fwd15: float | None,
        fwd30: float | None,
        ret5: float | None,
        ret15: float | None,
        ret30: float | None,
        max_up_15m: float | None,
        max_down_15m: float | None,
        label: str | None,
    ) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                INSERT INTO labeled_setups (
                    snapshot_id,
                    symbol,
                    timestamp,
                    price_at_snapshot,
                    future_price_5m,
                    future_price_15m,
                    future_price_30m,
                    ret_fwd_5m,
                    ret_fwd_15m,
                    ret_fwd_30m,
                    max_up_15m,
                    max_down_15m,
                    outcome_label
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row["id"],
                    row["symbol"],
                    row["timestamp"],
                    row["last_price"],
                    fwd5,
                    fwd15,
                    fwd30,
                    ret5,
                    ret15,
                    ret30,
                    max_up_15m,
                    max_down_15m,
                    label,
                ),
            )
