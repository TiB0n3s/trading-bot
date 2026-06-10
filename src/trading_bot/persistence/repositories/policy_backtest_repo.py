"""Repository boundary for policy backtest source rows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class PolicyBacktestRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def buy_rows(
        self,
        *,
        extra_sql: str = "",
        params: list[Any] | None = None,
        limit: int = 500,
    ):
        values = list(params or [])
        values.append(limit)
        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT
                    id,
                    timestamp,
                    symbol,
                    action,
                    signal_price,
                    approved,
                    rejection_reason,

                    market_bias,
                    market_bias_effective,
                    risk_level,
                    entry_quality,
                    trend_direction,
                    trend_strength,
                    momentum_direction,
                    momentum_pct,

                    session_trend_label,
                    session_trend_score,

                    prediction_score,
                    prediction_decision,

                    setup_label,
                    setup_policy_action,

                    buy_opportunity_score,
                    buy_opportunity_recommendation
                FROM trades
                WHERE LOWER(action) = 'buy'
                  AND signal_price IS NOT NULL
                  {extra_sql}
                ORDER BY id DESC
                LIMIT ?
                """,
                values,
            ).fetchall()
