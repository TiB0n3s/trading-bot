"""Repository boundary for research/training data access."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from db import DB_PATH


class TrainingDataRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)

    def _connect(self):
        con = sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True)
        con.row_factory = sqlite3.Row
        return con

    @staticmethod
    def _table_exists(con: sqlite3.Connection, table: str) -> bool:
        row = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone()
        return row is not None

    def table_count(
        self,
        table: str,
        where_sql: str = "",
        params: tuple[Any, ...] = (),
    ) -> int | None:
        with self._connect() as con:
            if not self._table_exists(con, table):
                return None
            sql = f"SELECT COUNT(*) AS n FROM {table}"
            if where_sql:
                sql += f" WHERE {where_sql}"
            return int(con.execute(sql, params).fetchone()["n"] or 0)

    def min_max(self, table: str, column: str) -> dict[str, Any]:
        with self._connect() as con:
            if not self._table_exists(con, table):
                return {"min": None, "max": None}
            row = con.execute(
                f"SELECT MIN({column}) AS min_value, MAX({column}) AS max_value FROM {table}"
            ).fetchone()
        return {"min": row["min_value"], "max": row["max_value"]}

    def distinct_feature_snapshot_symbols(
        self,
        where_sql: str = "",
        params: tuple[Any, ...] = (),
    ) -> int:
        with self._connect() as con:
            if not self._table_exists(con, "feature_snapshots"):
                return 0
            where = f"WHERE {where_sql}" if where_sql else ""
            row = con.execute(
                f"SELECT COUNT(DISTINCT symbol) AS n FROM feature_snapshots {where}",
                params,
            ).fetchone()
        return int(row["n"] or 0)

    def brain_source_rows(
        self,
        where_sql: str,
        params: tuple[Any, ...],
    ) -> list[sqlite3.Row]:
        with self._connect() as con:
            if not self._table_exists(con, "feature_snapshots"):
                return []

            event_count = "0"
            if self._table_exists(con, "daily_symbol_events"):
                event_count = """
                    (
                        SELECT COUNT(*)
                        FROM daily_symbol_events e
                        WHERE e.market_date = substr(fs.timestamp, 1, 10)
                          AND e.symbol = fs.symbol
                    )
                """

            has_labels = self._table_exists(con, "labeled_setups")
            has_context = self._table_exists(con, "daily_symbol_context")
            has_predictions = self._table_exists(con, "daily_symbol_predictions")

            label_join = """
                LEFT JOIN labeled_setups ls
                  ON ls.snapshot_id = fs.id
            """ if has_labels else ""
            context_join = """
                LEFT JOIN daily_symbol_context c
                  ON c.market_date = substr(fs.timestamp, 1, 10)
                 AND c.symbol = fs.symbol
            """ if has_context else ""
            prediction_join = """
                LEFT JOIN daily_symbol_predictions p
                  ON p.market_date = substr(fs.timestamp, 1, 10)
                 AND p.symbol = fs.symbol
            """ if has_predictions else ""

            query = f"""
                SELECT
                    fs.*,
                    substr(fs.timestamp, 1, 10) AS snapshot_date,
                    {event_count} AS event_count,
                    {('ls.outcome_label' if has_labels else 'NULL')} AS outcome_label,
                    {('ls.ret_fwd_15m' if has_labels else 'NULL')} AS ret_fwd_15m,
                    {('ls.ret_fwd_30m' if has_labels else 'NULL')} AS ret_fwd_30m,
                    {('c.bias' if has_context else 'NULL')} AS context_bias,
                    {('c.confidence' if has_context else 'NULL')} AS context_confidence,
                    {('c.risk_level' if has_context else 'NULL')} AS context_risk_level,
                    {('c.entry_quality' if has_context else 'NULL')} AS context_entry_quality,
                    {('c.catalyst_score' if has_context else 'NULL')} AS context_catalyst_score,
                    {('c.relative_strength_score' if has_context else 'NULL')} AS context_relative_strength_score,
                    {('p.prediction_score' if has_predictions else 'NULL')} AS prediction_score,
                    {('p.confidence' if has_predictions else 'NULL')} AS prediction_confidence,
                    {('p.sample_size' if has_predictions else 'NULL')} AS prediction_sample_size,
                    {('p.trend_label' if has_predictions else 'NULL')} AS prediction_trend_label,
                    {('p.timing_score' if has_predictions else 'NULL')} AS prediction_timing_score
                FROM feature_snapshots fs
                {label_join}
                {context_join}
                {prediction_join}
                WHERE {where_sql}
                ORDER BY fs.timestamp, fs.symbol, fs.id
            """
            return con.execute(query, params).fetchall()
