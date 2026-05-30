"""Pre-market research read repositories."""

from __future__ import annotations

from typing import Any

from db import DB_PATH, get_connection
from market_intelligence.intelligence_store import init_intelligence_tables


class PreMarketResearchRepository:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path

    def event_enrichment(self, market_date: str) -> dict[str, dict[str, Any]]:
        init_intelligence_tables()
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT symbol,
                       catalyst_score,
                       consumer_appetite_score,
                       revenue_impact_score,
                       profit_potential_score,
                       margin_risk_score,
                       supply_chain_risk_score,
                       materials_risk_score,
                       competitive_risk_score,
                       execution_risk_score
                FROM daily_symbol_context
                WHERE market_date = ?
                """,
                (market_date,),
            ).fetchall()

        out = {}
        for row in rows:
            out[row["symbol"]] = {
                "catalyst_score": row["catalyst_score"],
                "consumer_appetite_score": row["consumer_appetite_score"],
                "revenue_impact_score": row["revenue_impact_score"],
                "profit_potential_score": row["profit_potential_score"],
                "margin_risk_score": row["margin_risk_score"],
                "supply_chain_risk_score": row["supply_chain_risk_score"],
                "materials_risk_score": row["materials_risk_score"],
                "competitive_risk_score": row["competitive_risk_score"],
                "execution_risk_score": row["execution_risk_score"],
            }
        return out

    def latest_session_momentum(self, symbol: str) -> dict[str, Any]:
        with get_connection(self.db_path) as con:
            row = con.execute(
                """
                SELECT symbol, updated_at, trend_label, trend_score,
                       session_return_pct, momentum_5m_pct,
                       momentum_15m_pct, momentum_30m_pct,
                       distance_from_vwap_pct, reason
                FROM session_momentum
                WHERE symbol = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
        return dict(row) if row else {}

    def latest_prediction(self, symbol: str, market_date: str) -> dict[str, Any]:
        with get_connection(self.db_path) as con:
            row = con.execute(
                """
                SELECT symbol, prediction_score, probability_of_profit,
                       expected_pnl, expected_win_rate, confidence,
                       sample_size, timing_score, recommended_entry_timing,
                       recommended_exit_timing,
                       trend_score, trend_label, trend_regime,
                       trend_confidence, trend_similarity_sample_size,
                       reason, raw_json, updated_at
                FROM daily_symbol_predictions
                WHERE market_date = ?
                  AND symbol = ?
                ORDER BY updated_at DESC
                LIMIT 1
                """,
                (market_date, symbol),
            ).fetchone()
        return dict(row) if row else {}

    def prior_session_context(self, symbol: str, market_date: str) -> dict[str, Any]:
        with get_connection(self.db_path) as con:
            row = con.execute(
                """
                SELECT *
                FROM strong_day_participation
                WHERE symbol = ?
                  AND market_date < ?
                ORDER BY market_date DESC
                LIMIT 1
                """,
                (symbol, market_date),
            ).fetchone()
        return dict(row) if row else {}

    def strategy_memory_context(self, symbol: str) -> dict[str, Any]:
        with get_connection(self.db_path) as con:
            row = con.execute(
                """
                SELECT
                    COUNT(*) AS trades,
                    SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS wins,
                    SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END) AS losses,
                    SUM(COALESCE(realized_pnl, 0)) AS pnl,
                    AVG(realized_pnl) AS expectancy,
                    AVG(realized_pnl_pct) AS avg_pnl_pct
                FROM matched_trades
                WHERE symbol = ?
                """,
                (symbol,),
            ).fetchone()

        trades = int(row["trades"] or 0) if row else 0
        wins = int(row["wins"] or 0) if row else 0
        losses = int(row["losses"] or 0) if row else 0
        pnl = float(row["pnl"] or 0.0) if row else 0.0
        expectancy = float(row["expectancy"] or 0.0) if row else 0.0
        avg_pnl_pct = float(row["avg_pnl_pct"] or 0.0) if row else 0.0
        win_rate = wins / trades if trades else 0.0

        return {
            "trades": trades,
            "wins": wins,
            "losses": losses,
            "win_rate": round(win_rate, 4),
            "pnl": round(pnl, 2),
            "expectancy": round(expectancy, 2),
            "avg_pnl_pct": round(avg_pnl_pct, 4),
        }


_default_repository: PreMarketResearchRepository | None = None


def get_default_repository() -> PreMarketResearchRepository:
    global _default_repository
    if _default_repository is None:
        _default_repository = PreMarketResearchRepository()
    return _default_repository
