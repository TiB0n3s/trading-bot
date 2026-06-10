"""Repository reads for prediction drift and retraining triggers."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class PredictionDriftRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def table_exists(self, table_name: str) -> bool:
        with get_connection(self.db_path) as con:
            row = con.execute(
                """
                SELECT 1
                FROM sqlite_master
                WHERE type = 'table'
                  AND name = ?
                """,
                (table_name,),
            ).fetchone()
        return row is not None

    def available_prediction_outcome_dates(
        self,
        *,
        target_date: str | None,
        limit: int,
    ) -> list[str]:
        if not self.table_exists("daily_symbol_predictions") or not self.table_exists(
            "strong_day_participation"
        ):
            return []
        where = ""
        params: list[Any] = []
        if target_date:
            where = "AND p.market_date <= ?"
            params.append(target_date)
        params.append(limit)
        with get_connection(self.db_path) as con:
            rows = con.execute(
                f"""
                SELECT p.market_date
                FROM daily_symbol_predictions p
                JOIN strong_day_participation s
                  ON s.market_date = p.market_date
                 AND upper(s.symbol) = upper(p.symbol)
                WHERE p.prediction_score IS NOT NULL
                  {where}
                GROUP BY p.market_date
                ORDER BY p.market_date DESC
                LIMIT ?
                """,
                params,
            ).fetchall()
        return [str(row["market_date"]) for row in rows]

    def prediction_outcome_pairs(self, market_date: str) -> list[dict[str, Any]]:
        if not self.table_exists("daily_symbol_predictions") or not self.table_exists(
            "strong_day_participation"
        ):
            return []
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT
                    p.market_date,
                    upper(p.symbol) AS symbol,
                    p.prediction_score,
                    s.session_return_pct
                FROM daily_symbol_predictions p
                JOIN strong_day_participation s
                  ON s.market_date = p.market_date
                 AND upper(s.symbol) = upper(p.symbol)
                WHERE p.market_date = ?
                  AND p.prediction_score IS NOT NULL
                  AND s.session_return_pct IS NOT NULL
                ORDER BY upper(p.symbol)
                """,
                (market_date,),
            ).fetchall()
        return [dict(row) for row in rows]
