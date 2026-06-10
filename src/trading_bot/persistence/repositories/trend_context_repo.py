"""Repository boundary for historical trend context storage."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class HistoricalTrendContextRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def init_table(self) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS historical_trend_context (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    benchmark_symbol TEXT,
                    close_price REAL,
                    benchmark_close REAL,
                    trend_1d_pct REAL,
                    trend_3d_pct REAL,
                    trend_5d_pct REAL,
                    trend_10d_pct REAL,
                    trend_20d_pct REAL,
                    benchmark_1d_pct REAL,
                    benchmark_5d_pct REAL,
                    relative_strength_1d_pct REAL,
                    relative_strength_5d_pct REAL,
                    relative_strength_score REAL,
                    sma_5 REAL,
                    sma_10 REAL,
                    sma_20 REAL,
                    above_sma_5 INTEGER,
                    above_sma_10 INTEGER,
                    above_sma_20 INTEGER,
                    distance_from_sma_20_pct REAL,
                    volatility_5d_pct REAL,
                    avg_range_5d_pct REAL,
                    gap_pct REAL,
                    higher_highs_3d INTEGER,
                    higher_lows_3d INTEGER,
                    lower_highs_3d INTEGER,
                    lower_lows_3d INTEGER,
                    trend_label TEXT,
                    trend_regime TEXT,
                    trend_confidence TEXT,
                    trend_reason TEXT,
                    raw_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(market_date, symbol)
                )
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_historical_trend_context_date_symbol
                ON historical_trend_context(market_date, symbol)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_historical_trend_context_symbol_date
                ON historical_trend_context(symbol, market_date)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_historical_trend_context_label
                ON historical_trend_context(trend_label, trend_regime)
                """
            )

    def upsert_rows(self, rows: list[dict[str, Any]]) -> None:
        if not rows:
            return

        columns = list(rows[0].keys())
        placeholders = ", ".join("?" for _ in columns)
        update_cols = [col for col in columns if col not in ("market_date", "symbol", "created_at")]
        update_clause = ", ".join(f"{col}=excluded.{col}" for col in update_cols)

        sql = f"""
        INSERT INTO historical_trend_context ({", ".join(columns)})
        VALUES ({placeholders})
        ON CONFLICT(market_date, symbol) DO UPDATE SET
          {update_clause}
        """

        with get_connection(self.db_path) as con:
            con.executemany(sql, [[row[col] for col in columns] for row in rows])
            con.commit()
