"""Repository reads for prediction validation reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class PredictionValidationRepository:
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

    def load_predictions(self, target_date: str) -> list[dict[str, Any]]:
        if not self.table_exists("daily_symbol_predictions"):
            return []
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT market_date, symbol, prediction_score, probability_of_profit,
                       probability_of_order, expected_pnl, confidence, sample_size,
                       timing_score, recommended_entry_timing, trend_score,
                       trend_label, trend_regime, trend_confidence, reason
                FROM daily_symbol_predictions
                WHERE market_date = ?
                ORDER BY prediction_score DESC, symbol
                """,
                (target_date,),
            ).fetchall()
        return [dict(row) for row in rows]

    def load_signal_outcomes(self, target_date: str) -> dict[str, Any]:
        if not self.table_exists("historical_signal_outcomes"):
            return {}
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT symbol,
                       COUNT(*) AS signals,
                       SUM(CASE WHEN approved = 1 THEN 1 ELSE 0 END) AS approved,
                       SUM(CASE WHEN approved = 0 THEN 1 ELSE 0 END) AS rejected,
                       SUM(CASE WHEN realized_pnl IS NOT NULL THEN 1 ELSE 0 END) AS closed_signals,
                       SUM(COALESCE(realized_pnl, 0)) AS realized_pnl,
                       AVG(realized_pnl) AS avg_realized_pnl
                FROM historical_signal_outcomes
                WHERE market_date = ?
                GROUP BY symbol
                """,
                (target_date,),
            ).fetchall()
        return {row["symbol"]: dict(row) for row in rows}

    def load_matched_trades(self, target_date: str) -> dict[str, Any]:
        if not self.table_exists("matched_trades"):
            return {}
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT symbol,
                       COUNT(*) AS matched_trades,
                       SUM(COALESCE(realized_pnl, 0)) AS realized_pnl,
                       AVG(realized_pnl) AS avg_realized_pnl,
                       SUM(CASE WHEN won = 1 THEN 1 ELSE 0 END) AS wins,
                       SUM(CASE WHEN won = 0 THEN 1 ELSE 0 END) AS losses
                FROM matched_trades
                WHERE date(exit_timestamp) = ?
                GROUP BY symbol
                """,
                (target_date,),
            ).fetchall()
        return {row["symbol"]: dict(row) for row in rows}

    def load_strong_day_participation(self, target_date: str) -> dict[str, Any]:
        if not self.table_exists("strong_day_participation"):
            return {}
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT *
                FROM strong_day_participation
                WHERE market_date = ?
                  AND min_session_pct = (
                      SELECT MIN(min_session_pct)
                      FROM strong_day_participation
                      WHERE market_date = ?
                  )
                """,
                (target_date, target_date),
            ).fetchall()
        return {row["symbol"]: dict(row) for row in rows}

    def load_gate_ml_state_rows(self, target_date: str) -> list[dict[str, Any]]:
        if not self.table_exists("decision_snapshots"):
            return []
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT account_state_json
                FROM decision_snapshots
                WHERE substr(decision_time, 1, 10) = ?
                  AND lower(action) = 'buy'
                  AND account_state_json IS NOT NULL
                """,
                (target_date,),
            ).fetchall()
        return [dict(row) for row in rows]
