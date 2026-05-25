"""Read-only prediction provider interface.

This is a dormant serving-layer scaffold. Runtime code does not import it yet.
Future app.py integration should start read-only: log/dashboard only, no
decision influence.

Future runtime integration must honor the serving latency contract in
`ml_platform.governance`: prediction reads fail open to no prediction and must
never block signal processing.
"""

from __future__ import annotations

import sqlite3
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Protocol

from db import DB_PATH


@dataclass(frozen=True)
class PredictionView:
    market_date: str
    symbol: str
    prediction_score: float | None
    confidence: str | None
    sample_size: int | None
    trend_label: str | None
    timing_score: float | None
    reason: str | None
    provider: str = "sqlite_daily_symbol_predictions"
    runtime_effect: str = "none"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PredictionProvider(Protocol):
    """Read-only prediction provider contract."""

    latency_budget_ms: int
    timeout_ms: int

    def get_prediction(self, market_date: str, symbol: str) -> PredictionView | None:
        ...


class SQLitePredictionProvider:
    """Read daily_symbol_predictions without modifying runtime state."""

    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = Path(db_path)
        self.latency_budget_ms = 25
        self.timeout_ms = 50

    def get_prediction(self, market_date: str, symbol: str) -> PredictionView | None:
        with sqlite3.connect(f"file:{self.db_path}?mode=ro", uri=True) as con:
            con.row_factory = sqlite3.Row
            row = con.execute(
                """
                SELECT market_date, symbol, prediction_score, confidence,
                       sample_size, trend_label, timing_score, reason
                FROM daily_symbol_predictions
                WHERE market_date = ?
                  AND symbol = ?
                """,
                (market_date, symbol.upper()),
            ).fetchone()

        if not row:
            return None

        return PredictionView(
            market_date=row["market_date"],
            symbol=row["symbol"],
            prediction_score=row["prediction_score"],
            confidence=row["confidence"],
            sample_size=row["sample_size"],
            trend_label=row["trend_label"],
            timing_score=row["timing_score"],
            reason=row["reason"],
        )
