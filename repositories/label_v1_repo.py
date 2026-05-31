from __future__ import annotations

from pathlib import Path

from db import DB_PATH, get_connection


class LabelV1Repository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def feature_snapshot_columns(self) -> set[str]:
        with get_connection(self.db_path) as con:
            return {
                row["name"]
                for row in con.execute("PRAGMA table_info(feature_snapshots)").fetchall()
            }

    def stale_feature_snapshot_count(self) -> int:
        with get_connection(self.db_path) as con:
            row = con.execute(
                """
                SELECT COUNT(*) AS n
                FROM feature_snapshots
                WHERE COALESCE(is_stale, 0) != 0
                """
            ).fetchone()
        return int(row["n"] or 0)

    def label_count(self) -> int:
        with get_connection(self.db_path) as con:
            row = con.execute("SELECT COUNT(*) AS n FROM labeled_setups").fetchone()
        return int(row["n"] or 0)
