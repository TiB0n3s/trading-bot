"""Repository boundary for intelligence_learning_report.py reads."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class IntelligenceLearningReportRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def event_context_rows(
        self,
        start_date: str | None,
        end_date: str | None,
        symbol: str | None = None,
    ) -> list[Any]:
        params: list[Any] = []
        where = ["1=1"]

        if start_date:
            where.append("e.market_date >= ?")
            params.append(start_date)
        if end_date:
            where.append("e.market_date < ?")
            params.append(end_date)
        if symbol:
            where.append("e.symbol = ?")
            params.append(symbol.upper())

        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT
                    e.id AS event_id,
                    e.market_date,
                    e.symbol,
                    e.event_type,
                    e.expected_market_impact,
                    e.trade_relevance,
                    e.time_horizon,
                    e.confidence AS event_confidence,
                    e.consumer_appetite_score,
                    e.revenue_impact_score,
                    e.profit_potential_score,
                    e.margin_risk_score,
                    e.supply_chain_risk_score,
                    e.materials_risk_score,
                    e.regulatory_risk_score,
                    e.competitive_risk_score,
                    e.execution_risk_score,
                    e.macro_risk_score,
                    e.event_summary,

                    c.bias,
                    c.confidence AS context_confidence,
                    c.risk_level,
                    c.entry_quality,
                    c.avoid_type,
                    c.catalyst_score,
                    c.relative_strength_score,
                    c.daily_pct,
                    c.intraday_pct,
                    c.momentum_30m_pct,
                    c.sector_alignment,
                    c.index_alignment
                FROM daily_symbol_events e
                LEFT JOIN daily_symbol_context c
                  ON c.market_date = e.market_date
                 AND c.symbol = e.symbol
                WHERE {' AND '.join(where)}
                ORDER BY e.market_date, e.symbol, e.id
                """,
                params,
            ).fetchall()

    def trade_rows(self, market_date: str, symbol: str) -> list[Any]:
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT *
                FROM trades
                WHERE timestamp LIKE ?
                  AND symbol = ?
                """,
                (f"{market_date}%", symbol),
            ).fetchall()

    def matched_rows(self, market_date: str, symbol: str) -> list[Any]:
        try:
            with get_connection(self.db_path) as con:
                return con.execute(
                    """
                    SELECT *
                    FROM matched_trades
                    WHERE exit_timestamp LIKE ?
                      AND symbol = ?
                    """,
                    (f"{market_date}%", symbol),
                ).fetchall()
        except Exception:
            return []
