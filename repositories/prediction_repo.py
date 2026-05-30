"""Repository boundary for daily symbol predictions."""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

from db import DB_PATH


class PredictionRepository:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = Path(db_path or DB_PATH)

    def daily_predictions(self, market_date: str) -> list[dict[str, Any]]:
        if not self.db_path.exists():
            return []

        with sqlite3.connect(
            f"file:{self.db_path}?mode=ro",
            uri=True,
            timeout=0.05,
        ) as con:
            con.row_factory = sqlite3.Row
            exists = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_symbol_predictions'"
            ).fetchone()
            if not exists:
                return []
            rows = con.execute(
                """
                SELECT market_date, symbol, prediction_score, probability_of_profit,
                       probability_of_order, expected_pnl, confidence, sample_size,
                       reason, timing_score, recommended_entry_timing,
                       recommended_exit_timing, trend_score, trend_label,
                       trend_regime, trend_confidence, updated_at
                FROM daily_symbol_predictions
                WHERE market_date = ?
                """,
                (market_date,),
            ).fetchall()

        return [dict(row) for row in rows]
