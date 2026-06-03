"""Repository for observe-only candidate model shadow predictions."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from db import DB_PATH


class ShadowPredictionRepository:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path or DB_PATH)

    def _connect(self):
        return sqlite3.connect(self.db_path)

    def init_table(self) -> None:
        with self._connect() as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS shadow_predictions (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    prediction_time TEXT,
                    model_id TEXT NOT NULL,
                    artifact_path TEXT NOT NULL,
                    prediction_score REAL,
                    raw_prediction_score REAL,
                    feature_snapshot_id INTEGER,
                    feature_available_at TEXT,
                    generated_at TEXT NOT NULL,
                    runtime_effect TEXT NOT NULL,
                    UNIQUE(market_date, symbol, model_id, prediction_time)
                )
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_shadow_predictions_date_model
                ON shadow_predictions(market_date, model_id)
                """
            )

    def latest_feature_rows(
        self,
        *,
        market_date: str,
        feature_columns: list[str],
        limit: int = 500,
    ) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []
        with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            exists = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='feature_snapshots'"
            ).fetchone()
            if not exists:
                return []
            present = {
                row["name"]
                for row in con.execute("PRAGMA table_info(feature_snapshots)").fetchall()
            }
            selected_features = [
                col for col in feature_columns if col in present
            ]
            feature_sql = ", ".join(f"fs.{col}" for col in selected_features)
            if feature_sql:
                feature_sql = ", " + feature_sql
            feature_available = (
                "fs.feature_available_at"
                if "feature_available_at" in present
                else "fs.timestamp"
            )
            rows = con.execute(
                f"""
                WITH ranked AS (
                    SELECT
                        fs.id,
                        fs.symbol,
                        fs.timestamp,
                        {feature_available} AS feature_available_at,
                        ROW_NUMBER() OVER (
                            PARTITION BY fs.symbol
                            ORDER BY datetime(fs.timestamp) DESC, fs.id DESC
                        ) AS rn
                        {feature_sql}
                    FROM feature_snapshots fs
                    WHERE date(fs.timestamp) = date(?)
                )
                SELECT * FROM ranked
                WHERE rn = 1
                ORDER BY symbol
                LIMIT ?
                """,
                (market_date, int(limit)),
            ).fetchall()
        return [dict(row) for row in rows]

    def upsert_shadow_predictions(self, rows: list[dict[str, Any]]) -> int:
        if not rows:
            return 0
        self.init_table()
        with self._connect() as con:
            con.executemany(
                """
                INSERT INTO shadow_predictions (
                    market_date,
                    symbol,
                    prediction_time,
                    model_id,
                    artifact_path,
                    prediction_score,
                    raw_prediction_score,
                    feature_snapshot_id,
                    feature_available_at,
                    generated_at,
                    runtime_effect
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(market_date, symbol, model_id, prediction_time)
                DO UPDATE SET
                    prediction_score=excluded.prediction_score,
                    raw_prediction_score=excluded.raw_prediction_score,
                    feature_snapshot_id=excluded.feature_snapshot_id,
                    feature_available_at=excluded.feature_available_at,
                    generated_at=excluded.generated_at,
                    runtime_effect=excluded.runtime_effect
                """,
                [
                    (
                        row["market_date"],
                        row["symbol"],
                        row.get("prediction_time"),
                        row["model_id"],
                        row["artifact_path"],
                        row.get("prediction_score"),
                        row.get("raw_prediction_score"),
                        row.get("feature_snapshot_id"),
                        row.get("feature_available_at"),
                        row["generated_at"],
                        row["runtime_effect"],
                    )
                    for row in rows
                ],
            )
            return con.total_changes

    def load_shadow_prediction_outcomes(self, market_date: str) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []
        with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            tables = {
                row["name"]
                for row in con.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                ).fetchall()
            }
            if "shadow_predictions" not in tables:
                return []
            if "labeled_setups" in tables:
                label_columns = {
                    row["name"]
                    for row in con.execute("PRAGMA table_info(labeled_setups)").fetchall()
                }

                def expr(column: str) -> str:
                    return f"ls.{column}" if column in label_columns else "NULL"

                rows = con.execute(
                    f"""
                    SELECT
                        sp.market_date,
                        sp.symbol,
                        sp.prediction_time,
                        sp.model_id,
                        sp.prediction_score,
                        sp.raw_prediction_score,
                        sp.runtime_effect,
                        {expr("ret_fwd_5m")} AS ret_fwd_5m,
                        {expr("ret_fwd_15m")} AS ret_fwd_15m,
                        {expr("ret_fwd_30m")} AS ret_fwd_30m,
                        {expr("max_up_15m")} AS max_up_15m,
                        {expr("max_down_15m")} AS max_down_15m,
                        {expr("outcome_label")} AS outcome_label
                    FROM shadow_predictions sp
                    LEFT JOIN labeled_setups ls
                      ON ls.snapshot_id = sp.feature_snapshot_id
                    WHERE sp.market_date = ?
                    ORDER BY sp.model_id, sp.prediction_score DESC, sp.symbol
                    """,
                    (market_date,),
                ).fetchall()
            else:
                rows = con.execute(
                    """
                    SELECT
                        sp.market_date,
                        sp.symbol,
                        sp.prediction_time,
                        sp.model_id,
                        sp.prediction_score,
                        sp.raw_prediction_score,
                        sp.runtime_effect,
                        NULL AS ret_fwd_5m,
                        NULL AS ret_fwd_15m,
                        NULL AS ret_fwd_30m,
                        NULL AS max_up_15m,
                        NULL AS max_down_15m,
                        NULL AS outcome_label
                    FROM shadow_predictions sp
                    WHERE sp.market_date = ?
                    ORDER BY sp.model_id, sp.prediction_score DESC, sp.symbol
                    """,
                    (market_date,),
                ).fetchall()
        return [dict(row) for row in rows]
