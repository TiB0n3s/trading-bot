#!/usr/bin/env python3
"""
Structured news/event scoring model.

This module does not fetch news and does not trade.
It takes already-collected event facts and converts them into normalized,
learnable scores for daily_symbol_events.

Design:
- Deterministic and explainable.
- Conservative by default.
- Scores are 0–100 where higher usually means "more of that thing".
  Example:
    consumer_appetite_score high = stronger expected demand
    supply_chain_risk_score high = more risk
    competitive_risk_score high = more risk
"""

from __future__ import annotations

from dataclasses import dataclass, asdict
from typing import Any


VALID_EVENT_TYPES = {
    "product_launch",
    "earnings",
    "guidance",
    "analyst_action",
    "supply_chain",
    "regulatory",
    "lawsuit",
    "management_change",
    "macro_geopolitical",
    "industry_demand",
    "competitive_threat",
    "pricing_power",
    "margin_pressure",
    "capital_spending",
    "ai_infrastructure_demand",
}


BULLISH_WORDS = {
    "strong",
    "record",
    "surging",
    "accelerating",
    "robust",
    "positive",
    "upgrade",
    "beat",
    "raised",
    "demand",
    "sold out",
    "preorder",
    "preorders",
    "expansion",
    "growth",
    "margin expansion",
    "pricing power",
    "tailwind",
}

BEARISH_WORDS = {
    "weak",
    "slowing",
    "delay",
    "delayed",
    "shortage",
    "risk",
    "downgrade",
    "miss",
    "cut",
    "lawsuit",
    "probe",
    "investigation",
    "recall",
    "tariff",
    "sanction",
    "export control",
    "competition",
    "margin pressure",
    "supply constraint",
    "boycott",
}

SUPPLY_RISK_WORDS = {
    "shortage",
    "supplier",
    "supply",
    "materials",
    "chips",
    "semiconductor",
    "rare earth",
    "lithium",
    "tariff",
    "export control",
    "china",
    "taiwan",
    "shipping",
    "logistics",
    "factory",
    "strike",
}

REGULATORY_RISK_WORDS = {
    "regulation",
    "regulatory",
    "antitrust",
    "lawsuit",
    "probe",
    "investigation",
    "fine",
    "ban",
    "export control",
    "sanction",
    "tariff",
    "ftc",
    "doj",
    "eu",
}

COMPETITIVE_RISK_WORDS = {
    "competition",
    "competitor",
    "market share",
    "pricing pressure",
    "discount",
    "rival",
    "substitute",
    "android",
    "cloud competition",
    "gpu alternative",
}


@dataclass
class EventScores:
    consumer_appetite_score: float
    revenue_impact_score: float
    profit_potential_score: float
    margin_risk_score: float
    supply_chain_risk_score: float
    materials_risk_score: float
    regulatory_risk_score: float
    competitive_risk_score: float
    execution_risk_score: float
    macro_risk_score: float

    expected_market_impact: str
    trade_relevance: str
    time_horizon: str
    confidence: str
    scoring_reason: str


def clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, float(value)))


def text_score(text: str, words: set[str], per_hit: float = 8, cap: float = 40) -> float:
    t = text.lower()
    score = 0.0
    for word in words:
        if word in t:
            score += per_hit
    return clamp(score, 0, cap)


def normalize_event_type(value: str | None) -> str:
    if not value:
        return "industry_demand"
    v = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    return v if v in VALID_EVENT_TYPES else v


def score_event(event: dict[str, Any]) -> dict[str, Any]:
    """Return event payload enriched with normalized scores."""
    event_type = normalize_event_type(event.get("event_type"))
    summary = str(event.get("event_summary") or event.get("summary") or "")
    subtype = str(event.get("event_subtype") or "")
    product = str(event.get("product_name") or "")
    industry = str(event.get("industry") or "")
    segment = str(event.get("company_segment") or "")

    text = " ".join([summary, subtype, product, industry, segment]).lower()

    bullish = text_score(text, BULLISH_WORDS, per_hit=7, cap=45)
    bearish = text_score(text, BEARISH_WORDS, per_hit=7, cap=45)
    supply = text_score(text, SUPPLY_RISK_WORDS, per_hit=8, cap=55)
    regulatory = text_score(text, REGULATORY_RISK_WORDS, per_hit=9, cap=60)
    competitive = text_score(text, COMPETITIVE_RISK_WORDS, per_hit=8, cap=55)

    # Neutral baselines.
    consumer_appetite = 50
    revenue_impact = 50
    profit_potential = 50
    margin_risk = 35
    supply_chain_risk = 30
    materials_risk = 25
    regulatory_risk = 20
    competitive_risk = 30
    execution_risk = 30
    macro_risk = 25

    reason_bits = []

    if event_type == "product_launch":
        consumer_appetite += 10 + bullish * 0.6 - bearish * 0.3
        revenue_impact += 8 + bullish * 0.5 - bearish * 0.25
        profit_potential += 5 + bullish * 0.4 - supply * 0.2
        execution_risk += 8 + bearish * 0.3
        supply_chain_risk += supply
        materials_risk += supply * 0.7
        competitive_risk += competitive
        reason_bits.append("product_launch scoring applied")

    elif event_type == "earnings":
        revenue_impact += bullish * 0.8 - bearish * 0.8
        profit_potential += bullish * 0.8 - bearish * 0.8
        margin_risk += bearish * 0.7
        execution_risk += bearish * 0.5
        reason_bits.append("earnings scoring applied")

    elif event_type == "guidance":
        revenue_impact += bullish - bearish
        profit_potential += bullish - bearish
        execution_risk += bearish * 0.6
        reason_bits.append("guidance scoring applied")

    elif event_type == "analyst_action":
        revenue_impact += bullish * 0.5 - bearish * 0.5
        profit_potential += bullish * 0.5 - bearish * 0.5
        reason_bits.append("analyst_action scoring applied")

    elif event_type == "supply_chain":
        supply_chain_risk += 20 + supply
        materials_risk += 15 + supply * 0.8
        margin_risk += 10 + supply * 0.4
        execution_risk += 10 + supply * 0.4
        profit_potential -= supply * 0.3
        reason_bits.append("supply_chain scoring applied")

    elif event_type == "regulatory":
        regulatory_risk += 25 + regulatory
        execution_risk += 10 + regulatory * 0.3
        profit_potential -= regulatory * 0.3
        reason_bits.append("regulatory scoring applied")

    elif event_type == "macro_geopolitical":
        macro_risk += 25 + bearish
        supply_chain_risk += supply * 0.5
        materials_risk += supply * 0.4
        reason_bits.append("macro_geopolitical scoring applied")

    elif event_type == "competitive_threat":
        competitive_risk += 25 + competitive
        profit_potential -= competitive * 0.4
        margin_risk += competitive * 0.4
        reason_bits.append("competitive_threat scoring applied")

    elif event_type == "industry_demand":
        consumer_appetite += bullish * 0.6 - bearish * 0.4
        revenue_impact += bullish * 0.7 - bearish * 0.5
        profit_potential += bullish * 0.5 - bearish * 0.4
        reason_bits.append("industry_demand scoring applied")

    else:
        consumer_appetite += bullish * 0.4 - bearish * 0.3
        revenue_impact += bullish * 0.4 - bearish * 0.4
        profit_potential += bullish * 0.3 - bearish * 0.4
        margin_risk += bearish * 0.4
        reason_bits.append("generic scoring applied")

    # Explicit user-provided scores override model estimates when present.
    def override(name: str, current: float) -> float:
        value = event.get(name)
        if value is None:
            return current
        try:
            return float(value)
        except (TypeError, ValueError):
            return current

    scores = EventScores(
        consumer_appetite_score=clamp(override("consumer_appetite_score", consumer_appetite)),
        revenue_impact_score=clamp(override("revenue_impact_score", revenue_impact)),
        profit_potential_score=clamp(override("profit_potential_score", profit_potential)),
        margin_risk_score=clamp(override("margin_risk_score", margin_risk)),
        supply_chain_risk_score=clamp(override("supply_chain_risk_score", supply_chain_risk)),
        materials_risk_score=clamp(override("materials_risk_score", materials_risk)),
        regulatory_risk_score=clamp(override("regulatory_risk_score", regulatory_risk)),
        competitive_risk_score=clamp(override("competitive_risk_score", competitive_risk)),
        execution_risk_score=clamp(override("execution_risk_score", execution_risk)),
        macro_risk_score=clamp(override("macro_risk_score", macro_risk)),
        expected_market_impact="neutral",
        trade_relevance="watch_only",
        time_horizon=str(event.get("time_horizon") or default_time_horizon(event_type)),
        confidence=str(event.get("confidence") or infer_confidence(summary, bullish, bearish)),
        scoring_reason="; ".join(reason_bits),
    )

    upside = (
        scores.consumer_appetite_score * 0.25
        + scores.revenue_impact_score * 0.30
        + scores.profit_potential_score * 0.25
    )
    risk = (
        scores.margin_risk_score * 0.15
        + scores.supply_chain_risk_score * 0.15
        + scores.regulatory_risk_score * 0.15
        + scores.competitive_risk_score * 0.15
        + scores.execution_risk_score * 0.15
        + scores.macro_risk_score * 0.10
    )
    net = upside - risk

    if net >= 25:
        impact = "strongly_bullish"
        relevance = "potential_catalyst"
    elif net >= 12:
        impact = "moderately_bullish"
        relevance = "watch_for_confirmation"
    elif net <= -20:
        impact = "strongly_bearish"
        relevance = "risk_alert"
    elif net <= -8:
        impact = "moderately_bearish"
        relevance = "caution"
    else:
        impact = "neutral"
        relevance = "watch_only"

    # Let explicit values override labels if provided.
    if event.get("expected_market_impact"):
        impact = str(event["expected_market_impact"])
    if event.get("trade_relevance"):
        relevance = str(event["trade_relevance"])

    out = dict(event)
    out["event_type"] = event_type
    out.update(asdict(scores))
    out["expected_market_impact"] = impact
    out["trade_relevance"] = relevance
    out["net_event_score"] = round(net, 2)

    return out


def default_time_horizon(event_type: str) -> str:
    if event_type in ("product_launch", "industry_demand", "capital_spending", "ai_infrastructure_demand"):
        return "weeks_to_quarters"
    if event_type in ("earnings", "guidance", "analyst_action"):
        return "days_to_weeks"
    if event_type in ("regulatory", "lawsuit", "macro_geopolitical"):
        return "weeks_to_months"
    return "days_to_weeks"


def infer_confidence(summary: str, bullish: float, bearish: float) -> str:
    if len(summary) < 40:
        return "low"
    if bullish >= 20 or bearish >= 20:
        return "medium"
    return "low"
