"""Pre-market research read repositories."""

from __future__ import annotations

import json
from typing import Any

from db import DB_PATH, get_connection

from market_intelligence.intelligence_store import init_intelligence_tables
from market_intelligence.source_reliability import (
    classify_source,
    confidence_cap_for_sources,
)


class PreMarketResearchRepository:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path

    def event_enrichment(self, market_date: str) -> dict[str, dict[str, Any]]:
        init_intelligence_tables(self.db_path)
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT c.symbol,
                       c.catalyst_score,
                       c.consumer_appetite_score,
                       c.revenue_impact_score,
                       c.profit_potential_score,
                       c.margin_risk_score,
                       c.supply_chain_risk_score,
                       c.materials_risk_score,
                       c.competitive_risk_score,
                       c.execution_risk_score,
                       e.event_count,
                       e.source_count,
                       e.sources,
                       e.trusted_source_count,
                       e.source_tiers,
                       c.raw_json AS context_raw_json,
                       e.raw_events_json
                FROM daily_symbol_context c
                LEFT JOIN (
                    SELECT symbol,
                           COUNT(*) AS event_count,
                           COUNT(DISTINCT COALESCE(source, 'unknown')) AS source_count,
                           GROUP_CONCAT(DISTINCT COALESCE(source, 'unknown')) AS sources,
                           GROUP_CONCAT(raw_json, '|||') AS raw_events_json,
                           0 AS trusted_source_count,
                           NULL AS source_tiers
                    FROM daily_symbol_events
                    WHERE market_date = ?
                    GROUP BY symbol
                ) e ON e.symbol = c.symbol
                WHERE c.market_date = ?
                """,
                (market_date, market_date),
            ).fetchall()

        out = {}
        for row in rows:
            raw_context = {}
            try:
                loaded = json.loads(row["context_raw_json"] or "{}")
                raw_context = loaded if isinstance(loaded, dict) else {}
            except Exception:
                raw_context = {}
            raw_events = []
            for raw in str(row["raw_events_json"] or "").split("|||"):
                if not raw:
                    continue
                try:
                    loaded = json.loads(raw)
                    if isinstance(loaded, dict):
                        raw_events.append(loaded)
                except Exception:
                    pass
            sources = [source for source in str(row["sources"] or "").split(",") if source]
            source_tiers = []
            trusted_source_count = 0
            for source in sources:
                source_policy = classify_source(source)
                tier = str(source_policy["source_tier"])
                source_tiers.append(tier)
                trusted_source_count += int(bool(source_policy["trusted_source"]))
            confidence_cap = confidence_cap_for_sources(
                source_tiers,
                int(row["source_count"] or 0),
            )
            event_context = raw_context.get("event_context")
            if not isinstance(event_context, dict):
                intent_directions = sorted(
                    {
                        str(event.get("intent_direction"))
                        for event in raw_events
                        if event.get("intent_direction")
                    }
                )
                intent_categories = sorted(
                    {
                        str(event.get("intent_category"))
                        for event in raw_events
                        if event.get("intent_category")
                    }
                )
                intent_scopes = sorted(
                    {
                        str(event.get("intent_scope"))
                        for event in raw_events
                        if event.get("intent_scope")
                    }
                )
                confirmation_statuses = sorted(
                    {
                        str(event.get("confirmation_status"))
                        for event in raw_events
                        if event.get("confirmation_status")
                    }
                )
                missing_evidence = sorted(
                    {
                        str(item)
                        for event in raw_events
                        for item in (
                            event.get("missing_evidence")
                            if isinstance(event.get("missing_evidence"), list)
                            else []
                        )
                        if item
                    }
                )
                linked_context_symbols = sorted(
                    {
                        str(event.get("symbol")).upper()
                        for event in raw_events
                        if event.get("context_only") is True and event.get("symbol")
                    }
                )
                linked_context_event_count = sum(
                    1 for event in raw_events if event.get("context_only") is True
                )
                event_context = {
                    "event_intent_version": "event_intent_aggregate_v1",
                    "available": bool(raw_events),
                    "event_count": row["event_count"],
                    "linked_context_symbols": linked_context_symbols,
                    "linked_context_event_count": linked_context_event_count,
                    "ai_interpretation_count": sum(
                        1 for event in raw_events if isinstance(event.get("ai_event_context"), dict)
                    ),
                    "ai_event_context_version": "ai_event_context_aggregate_v1",
                    "ai_providers": sorted(
                        {
                            str((event.get("ai_event_context") or {}).get("provider"))
                            for event in raw_events
                            if isinstance(event.get("ai_event_context"), dict)
                            and (event.get("ai_event_context") or {}).get("provider")
                        }
                    ),
                    "ai_intents": sorted(
                        {
                            str((event.get("ai_event_context") or {}).get("intent"))
                            for event in raw_events
                            if isinstance(event.get("ai_event_context"), dict)
                            and (event.get("ai_event_context") or {}).get("intent")
                        }
                    ),
                    "ai_market_alignment": sorted(
                        {
                            str((event.get("ai_event_context") or {}).get("market_alignment"))
                            for event in raw_events
                            if isinstance(event.get("ai_event_context"), dict)
                            and (event.get("ai_event_context") or {}).get("market_alignment")
                        }
                    ),
                    "ai_information_novelty": sorted(
                        {
                            str((event.get("ai_event_context") or {}).get("information_novelty"))
                            for event in raw_events
                            if isinstance(event.get("ai_event_context"), dict)
                            and (event.get("ai_event_context") or {}).get("information_novelty")
                        }
                    ),
                    "ai_positioning_effect": sorted(
                        {
                            str((event.get("ai_event_context") or {}).get("positioning_effect"))
                            for event in raw_events
                            if isinstance(event.get("ai_event_context"), dict)
                            and (event.get("ai_event_context") or {}).get("positioning_effect")
                        }
                    ),
                    "ai_earnings_positioning_context": sorted(
                        {
                            str(
                                (event.get("ai_event_context") or {}).get(
                                    "earnings_positioning_context"
                                )
                            )
                            for event in raw_events
                            if isinstance(event.get("ai_event_context"), dict)
                            and (event.get("ai_event_context") or {}).get(
                                "earnings_positioning_context"
                            )
                        }
                    ),
                    "ai_earnings_information_surprise": sorted(
                        {
                            str(
                                (event.get("ai_event_context") or {}).get(
                                    "earnings_information_surprise"
                                )
                            )
                            for event in raw_events
                            if isinstance(event.get("ai_event_context"), dict)
                            and (event.get("ai_event_context") or {}).get(
                                "earnings_information_surprise"
                            )
                        }
                    ),
                    "ai_summaries": [
                        str((event.get("ai_event_context") or {}).get("summary"))
                        for event in raw_events
                        if isinstance(event.get("ai_event_context"), dict)
                        and (event.get("ai_event_context") or {}).get("summary")
                    ][:5],
                    "intent_directions": intent_directions,
                    "intent_categories": intent_categories,
                    "intent_scopes": intent_scopes,
                    "confirmation_statuses": confirmation_statuses,
                    "missing_evidence": missing_evidence,
                    "authority": "context_only_no_standalone_buy_authority",
                }
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
                "event_count": row["event_count"],
                "source_count": row["source_count"],
                "sources": sources,
                "trusted_source_count": trusted_source_count,
                "source_tiers": sorted(set(source_tiers)),
                "confidence_cap": confidence_cap,
                "event_context": event_context,
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
