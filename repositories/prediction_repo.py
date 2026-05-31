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

    def table_exists(self, table_name: str) -> bool:
        if not self.db_path.exists():
            return False

        with sqlite3.connect(
            f"file:{self.db_path}?mode=ro",
            uri=True,
            timeout=0.05,
        ) as con:
            con.row_factory = sqlite3.Row
            row = con.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table_name,),
            ).fetchone()
        return row is not None

    def intelligence_prediction_report_rows(
        self,
        market_date: str,
        symbol: str | None = None,
    ) -> list[sqlite3.Row]:
        params: list[Any] = [market_date]
        symbol_sql = ""
        if symbol:
            symbol_sql = "AND p.symbol = ?"
            params.append(symbol.upper())

        strong_join = ""
        strong_columns = """
                NULL AS strong_session_return_pct,
                NULL AS strong_primary_status,
                NULL AS strong_primary_blocker,
                NULL AS strong_auto_buy_candidates,
                NULL AS strong_auto_buy_max_score
        """
        if self.table_exists("strong_day_participation"):
            strong_columns = """
                s.session_return_pct AS strong_session_return_pct,
                s.primary_status AS strong_primary_status,
                s.primary_blocker AS strong_primary_blocker,
                s.auto_buy_candidate_count AS strong_auto_buy_candidates,
                s.auto_buy_max_score AS strong_auto_buy_max_score
            """
            strong_join = """
            LEFT JOIN strong_day_participation s
              ON s.market_date = p.market_date
             AND s.symbol = p.symbol
             AND s.min_session_pct = (
                 SELECT MIN(min_session_pct)
                 FROM strong_day_participation
                 WHERE market_date = p.market_date
             )
            """

        with sqlite3.connect(
            f"file:{self.db_path}?mode=ro",
            uri=True,
            timeout=0.05,
        ) as con:
            con.row_factory = sqlite3.Row
            return con.execute(
                f"""
                SELECT
                    p.*,
                    c.bias,
                    c.risk_level,
                    c.entry_quality,
                    c.catalyst_score,
                    c.supply_chain_risk_score,
                    c.competitive_risk_score,
                    {strong_columns}
                FROM daily_symbol_predictions p
                LEFT JOIN daily_symbol_context c
                  ON c.market_date = p.market_date
                 AND c.symbol = p.symbol
                {strong_join}
                WHERE p.market_date = ?
                  {symbol_sql}
                ORDER BY p.prediction_score DESC, p.symbol
                """,
                tuple(params),
            ).fetchall()
