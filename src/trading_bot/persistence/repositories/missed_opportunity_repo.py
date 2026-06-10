"""Repository reads for missed opportunity reports."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class MissedOpportunityRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def load_rejections(
        self,
        target_date: str,
        symbol: str | None = None,
        category_filter: str | None = None,
        limit: int = 80,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [f"{target_date}%"]
        extra = ""

        if symbol:
            extra += " AND symbol = ?"
            params.append(symbol.upper())

        if category_filter:
            extra += " AND rejection_reason LIKE ?"
            params.append(f"{category_filter}:%")

        with get_connection(self.db_path) as con:
            rows = con.execute(
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
                    trend_direction,
                    trend_strength,
                    momentum_direction,
                    momentum_pct,

                    session_trend_label,
                    prediction_score,
                    prediction_decision,
                    setup_label,
                    setup_policy_action,
                    buy_opportunity_score,
                    buy_opportunity_recommendation
                FROM trades
                WHERE approved = 0
                  AND LOWER(action) = 'buy'
                  AND signal_price IS NOT NULL
                  AND rejection_reason IS NOT NULL
                  AND timestamp LIKE ?
                  {extra}
                ORDER BY id DESC
                LIMIT ?
                """,
                params + [limit],
            ).fetchall()

        return [dict(row) for row in rows]
