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

from market_intelligence.source_reliability import classify_source, confidence_cap_for_sources


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
    "supplier_signal",
    "customer_contract",
    "strategic_partnership",
    "leadership_personnel",
    "mna_deal_chatter",
    "insider_transaction",
    "congressional_trade_disclosure",
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

DEAL_WORDS = {
    "acquisition",
    "acquire",
    "merger",
    "takeover",
    "buyout",
    "deal",
    "strategic investment",
    "joint venture",
    "partnership",
    "partner",
}

LEADERSHIP_WORDS = {
    "ceo",
    "cfo",
    "chief executive",
    "chief financial",
    "resigns",
    "resignation",
    "steps down",
    "appointed",
    "names",
    "hires",
}

INSIDER_WORDS = {
    "insider buying",
    "insider bought",
    "insider purchase",
    "insider selling",
    "insider sold",
    "insider sale",
    "director bought",
    "director sold",
}

CONGRESSIONAL_DISCLOSURE_WORDS = {
    "congress",
    "congressional",
    "senator",
    "representative",
    "lawmaker",
    "politician",
    "stock act",
    "periodic transaction report",
    "public financial disclosure",
    "house disclosure",
    "senate disclosure",
    "quiver quantitative",
}

CUSTOMER_CONTRACT_WORDS = {
    "contract",
    "customer",
    "order",
    "booking",
    "backlog",
    "purchase agreement",
    "supply agreement",
    "selected",
    "award",
    "awarded",
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


TRUSTED_BULLISH_SOURCE_TIERS = {
    "official",
    "confirmed_financial_news",
    "deep_analysis",
}

EVENT_INTENT_VERSION = "event_intent_v1"


def clamp(value: float, low: float = 0, high: float = 100) -> float:
    return max(low, min(high, float(value)))


_NEGATION_WORDS = {"no", "not", "without", "reduces", "resolved", "eliminates", "avoids"}


def has_negation_near(text: str, keyword: str, window: int = 4) -> bool:
    """Return True if a negation word precedes keyword within window words.

    Handles both single-word and multi-word keywords (e.g. 'supply chain risk').
    Searches for the keyword token sequence and checks the preceding window.
    """
    words = text.lower().split()
    kw_tokens = keyword.lower().split()
    kw_len = len(kw_tokens)
    for i in range(len(words) - kw_len + 1):
        if words[i : i + kw_len] == kw_tokens:
            context = words[max(0, i - window) : i]
            if any(n in context for n in _NEGATION_WORDS):
                return True
    return False


def text_score(text: str, words: set[str], per_hit: float = 8, cap: float = 40) -> float:
    t = text.lower()
    score = 0.0
    for word in words:
        if word in t:
            if has_negation_near(t, word):
                score -= per_hit * 0.5  # negated phrase reduces rather than adds
            else:
                score += per_hit
    return clamp(score, 0, cap)


def normalize_event_type(value: str | None) -> str:
    if not value:
        return "industry_demand"
    v = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    return v if v in VALID_EVENT_TYPES else v


def _is_trusted_bullish_source(event: dict[str, Any]) -> bool:
    if event.get("trusted_source") is True:
        return True
    return str(event.get("source_tier") or "") in TRUSTED_BULLISH_SOURCE_TIERS


def _source_tier(event: dict[str, Any]) -> str:
    return str(event.get("source_tier") or "unknown")


def _search_scope(event: dict[str, Any]) -> str:
    return str(event.get("search_scope") or event.get("relevance_scope") or "unknown")


def _confirmation_status(event: dict[str, Any], source_tier: str) -> str:
    explicit = str(event.get("confirmation_status") or "").strip().lower()
    if explicit:
        return explicit
    if source_tier == "official":
        return "official_confirmed"
    if source_tier in TRUSTED_BULLISH_SOURCE_TIERS:
        return "reputable_reported"
    if source_tier in ("medium_confidence",):
        return "needs_confirmation"
    return "unconfirmed"


def _intent_scope(event: dict[str, Any], event_type: str) -> str:
    scope = _search_scope(event)
    if scope in ("company_direct", "direct", "symbol_direct"):
        return "direct_company"
    if scope in ("company_peripheral", "peripheral", "supplier", "customer"):
        return "peripheral_company"
    if event_type in ("supplier_signal", "customer_contract", "leadership_personnel", "mna_deal_chatter", "insider_transaction"):
        return "peripheral_company"
    if event_type in ("congressional_trade_disclosure",):
        return "public_official_disclosure"
    if event_type in ("macro_geopolitical",):
        return "macro"
    return "direct_company" if event.get("symbol") else "market_wide"


def _event_intent_category(event_type: str, scores: EventScores, impact: str) -> str:
    if event_type in ("earnings", "guidance"):
        return "company_fundamental_update"
    if event_type in ("supplier_signal", "supply_chain"):
        return "supply_chain_or_input_risk"
    if event_type in ("customer_contract", "industry_demand", "ai_infrastructure_demand"):
        return "demand_or_revenue_signal"
    if event_type in ("leadership_personnel",):
        return "management_execution_signal"
    if event_type in ("mna_deal_chatter", "strategic_partnership"):
        return "strategic_transaction_signal"
    if event_type in ("regulatory", "lawsuit", "macro_geopolitical"):
        return "external_risk_signal"
    if event_type in ("insider_transaction",):
        return "insider_activity_signal"
    if event_type in ("congressional_trade_disclosure",):
        return "public_official_trade_disclosure"
    if impact in ("strongly_bearish", "moderately_bearish"):
        return "risk_signal"
    if impact in ("strongly_bullish", "moderately_bullish"):
        return "upside_catalyst_signal"
    return "context_signal"


def interpret_event_intent(
    *,
    event: dict[str, Any],
    event_type: str,
    scores: EventScores,
    impact: str,
    relevance: str,
    net_score: float,
    reason_bits: list[str],
) -> dict[str, Any]:
    """Build a structured event-intent interpretation.

    This is intentionally deterministic and advisory. It interprets event
    intent from event type, source quality, scope, and score dimensions rather
    than just headline keywords.
    """
    source_tier = _source_tier(event)
    source_tiers = [source_tier]
    confirmation_status = _confirmation_status(event, source_tier)
    confidence_cap = confidence_cap_for_sources(source_tiers, 1)
    scope = _intent_scope(event, event_type)
    risk_dimensions = {
        "margin": scores.margin_risk_score,
        "supply_chain": scores.supply_chain_risk_score,
        "materials": scores.materials_risk_score,
        "regulatory": scores.regulatory_risk_score,
        "competitive": scores.competitive_risk_score,
        "execution": scores.execution_risk_score,
        "macro": scores.macro_risk_score,
    }
    upside_dimensions = {
        "consumer_appetite": scores.consumer_appetite_score,
        "revenue": scores.revenue_impact_score,
        "profit": scores.profit_potential_score,
    }
    dominant_risk = max(risk_dimensions.items(), key=lambda item: item[1])
    dominant_upside = max(upside_dimensions.items(), key=lambda item: item[1])
    if impact in ("strongly_bullish", "moderately_bullish"):
        direction = "constructive"
    elif impact in ("strongly_bearish", "moderately_bearish"):
        direction = "risk_negative"
    elif dominant_risk[1] >= 65:
        direction = "risk_watch"
    elif dominant_upside[1] >= 65:
        direction = "constructive_watch"
    else:
        direction = "neutral_context"

    evidence = [
        f"event_type={event_type}",
        f"source_tier={source_tier}",
        f"scope={scope}",
        f"dominant_upside={dominant_upside[0]}:{round(float(dominant_upside[1]), 2)}",
        f"dominant_risk={dominant_risk[0]}:{round(float(dominant_risk[1]), 2)}",
        f"net_event_score={round(float(net_score), 2)}",
    ]
    if reason_bits:
        evidence.extend(reason_bits[:3])

    missing_evidence = []
    if confirmation_status in ("unconfirmed", "needs_confirmation"):
        missing_evidence.append("official_or_second_reputable_source")
    if scope == "peripheral_company":
        missing_evidence.append("direct_company_confirmation")
    if source_tier in ("unclassified", "low_confidence", "unknown"):
        missing_evidence.append("trusted_source_attribution")
    if event_type == "congressional_trade_disclosure":
        disclosure_limitations = [
            "delayed_stock_act_reporting",
            "broad_dollar_range_not_exact_size",
            "may_include_spouse_or_dependent_trade",
            "does_not_prove_trade_was_informed_or_timely",
        ]
        missing_evidence.extend(disclosure_limitations)
        if source_tier != "official":
            missing_evidence.append("official_house_or_senate_filing")

    return {
        "event_intent_version": EVENT_INTENT_VERSION,
        "intent_category": _event_intent_category(event_type, scores, impact),
        "intent_direction": direction,
        "intent_scope": scope,
        "confirmation_status": confirmation_status,
        "confidence_cap": confidence_cap,
        "authority": "context_only_no_standalone_buy_authority",
        "expected_market_impact": impact,
        "trade_relevance": relevance,
        "dominant_upside_dimension": dominant_upside[0],
        "dominant_risk_dimension": dominant_risk[0],
        "evidence": evidence,
        "missing_evidence": missing_evidence,
    }


def score_event(event: dict[str, Any]) -> dict[str, Any]:
    """Return event payload enriched with normalized scores."""
    event = dict(event)
    if not event.get("source_tier"):
        source_policy = classify_source(event.get("source"), url=event.get("source_url"))
        event.update({k: v for k, v in source_policy.items() if event.get(k) is None})

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

    elif event_type == "supplier_signal":
        supply_chain_risk += 12 + supply * 0.8 + bearish * 0.4
        materials_risk += 10 + supply * 0.7
        execution_risk += 8 + bearish * 0.4
        revenue_impact += bullish * 0.3 - bearish * 0.4
        profit_potential += bullish * 0.2 - bearish * 0.4
        reason_bits.append("supplier_signal scoring applied")

    elif event_type == "customer_contract":
        contract = text_score(text, CUSTOMER_CONTRACT_WORDS, per_hit=7, cap=35)
        revenue_impact += contract * 0.8 + bullish * 0.4 - bearish * 0.4
        profit_potential += contract * 0.4 + bullish * 0.3 - bearish * 0.3
        execution_risk += bearish * 0.4
        reason_bits.append("customer_contract scoring applied")

    elif event_type == "strategic_partnership":
        deal = text_score(text, DEAL_WORDS, per_hit=7, cap=35)
        revenue_impact += deal * 0.4 + bullish * 0.3 - bearish * 0.3
        profit_potential += deal * 0.3 + bullish * 0.2 - bearish * 0.3
        execution_risk += 5 + bearish * 0.4
        reason_bits.append("strategic_partnership scoring applied")

    elif event_type == "leadership_personnel":
        leadership = text_score(text, LEADERSHIP_WORDS, per_hit=7, cap=35)
        execution_risk += 8 + leadership * 0.4 + bearish * 0.6
        profit_potential += bullish * 0.2 - bearish * 0.5
        reason_bits.append("leadership_personnel scoring applied")

    elif event_type == "mna_deal_chatter":
        deal = text_score(text, DEAL_WORDS, per_hit=7, cap=35)
        revenue_impact += deal * 0.3 + bullish * 0.2 - bearish * 0.2
        profit_potential += deal * 0.25 + bullish * 0.2 - bearish * 0.2
        execution_risk += 10 + bearish * 0.4
        regulatory_risk += regulatory * 0.3
        reason_bits.append("mna_deal_chatter scoring applied")

    elif event_type == "insider_transaction":
        insider = text_score(text, INSIDER_WORDS, per_hit=7, cap=35)
        if "sell" in text or "sold" in text or "sale" in text:
            execution_risk += 8 + insider * 0.5
            profit_potential -= insider * 0.3
        elif "buy" in text or "bought" in text or "purchase" in text:
            profit_potential += insider * 0.2
        reason_bits.append("insider_transaction scoring applied")

    elif event_type == "congressional_trade_disclosure":
        disclosure = text_score(text, CONGRESSIONAL_DISCLOSURE_WORDS, per_hit=6, cap=30)
        # STOCK Act disclosures are delayed and range-based. They are useful
        # as governance/context signals, not as copy-trading evidence.
        execution_risk += 4 + disclosure * 0.15
        macro_risk += disclosure * 0.10
        if "sell" in text or "sold" in text or "sale" in text:
            execution_risk += 4
        elif "buy" in text or "bought" in text or "purchase" in text:
            profit_potential += 1
        reason_bits.append("congressional_trade_disclosure context-only scoring applied")

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
        confidence=str(event.get("confidence") or infer_confidence(
            summary, bullish, bearish,
            event_type=event_type,
            net_score=bullish - bearish,
        )),
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
    raw_net = upside - risk
    neutral_upside = 50 * 0.25 + 50 * 0.30 + 50 * 0.25
    neutral_risk = (
        35 * 0.15
        + 30 * 0.15
        + 20 * 0.15
        + 30 * 0.15
        + 30 * 0.15
        + 25 * 0.10
    )
    # A neutral event should score neutral. The previous raw upside-risk spread
    # had a positive baseline, which made weak/unrelated headlines look bullish.
    net = raw_net - (neutral_upside - neutral_risk)

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

    trusted_bullish_source = _is_trusted_bullish_source(event)
    source_tier = _source_tier(event)
    peripheral_types = {
        "supplier_signal",
        "customer_contract",
        "strategic_partnership",
        "leadership_personnel",
        "mna_deal_chatter",
        "insider_transaction",
        "congressional_trade_disclosure",
    }
    if impact in ("strongly_bullish", "moderately_bullish") and not trusted_bullish_source:
        if net < 20 or source_tier in ("unclassified", "low_confidence", "unknown"):
            impact = "neutral"
            relevance = "watch_for_confirmation" if net >= 12 else "watch_only"
            reason_bits.append(
                f"bullish inference capped by source reliability tier={source_tier}"
            )
        elif impact == "strongly_bullish":
            impact = "moderately_bullish"
            relevance = "watch_for_confirmation"
            reason_bits.append(
                f"strong bullish inference capped by source reliability tier={source_tier}"
            )
    if event_type in peripheral_types:
        if impact == "strongly_bullish":
            impact = "moderately_bullish"
            relevance = "watch_for_confirmation"
            reason_bits.append("peripheral event capped below strong bullish")
        if event_type in ("mna_deal_chatter", "insider_transaction") and not trusted_bullish_source:
            impact = "neutral"
            relevance = "watch_for_confirmation" if net >= 8 else "watch_only"
            reason_bits.append("rumor-sensitive peripheral event requires trusted confirmation")
    if event_type == "congressional_trade_disclosure":
        if impact in ("strongly_bullish", "moderately_bullish"):
            impact = "neutral"
        relevance = "watch_only"
        reason_bits.append(
            "congressional disclosures are delayed/range-based and never standalone trade authority"
        )

    # Let explicit values override labels if provided.
    if event.get("expected_market_impact"):
        impact = str(event["expected_market_impact"])
    if event.get("trade_relevance"):
        relevance = str(event["trade_relevance"])
    if event_type == "congressional_trade_disclosure":
        # Do not let manual overrides or aggregator payloads convert delayed
        # disclosures into directional authority.
        if impact in ("strongly_bullish", "moderately_bullish"):
            impact = "neutral"
        relevance = "watch_only"

    intent = interpret_event_intent(
        event=event,
        event_type=event_type,
        scores=scores,
        impact=impact,
        relevance=relevance,
        net_score=net,
        reason_bits=reason_bits,
    )

    out = dict(event)
    out["event_type"] = event_type
    out.update(asdict(scores))
    out.update(intent)
    out["event_intent"] = intent
    out["expected_market_impact"] = impact
    out["trade_relevance"] = relevance
    out["net_event_score"] = round(net, 2)
    out["scoring_reason"] = "; ".join(reason_bits)

    return out


def default_time_horizon(event_type: str) -> str:
    if event_type in (
        "product_launch",
        "industry_demand",
        "capital_spending",
        "ai_infrastructure_demand",
        "supplier_signal",
        "customer_contract",
        "strategic_partnership",
    ):
        return "weeks_to_quarters"
    if event_type in ("earnings", "guidance", "analyst_action", "leadership_personnel", "insider_transaction"):
        return "days_to_weeks"
    if event_type in ("congressional_trade_disclosure",):
        return "delayed_disclosure_context"
    if event_type in ("regulatory", "lawsuit", "macro_geopolitical", "mna_deal_chatter"):
        return "weeks_to_months"
    return "days_to_weeks"


def infer_confidence(
    summary: str,
    bullish: float,
    bearish: float,
    event_type: str = "",
    net_score: float = 0,
) -> str:
    if event_type in ("earnings", "guidance") and (bullish >= 28 or bearish >= 28):
        return "high"
    if len(summary) >= 80 and (bullish >= 21 or bearish >= 21):
        return "medium"
    if len(summary) >= 40 and abs(net_score) >= 15:
        return "medium"
    return "low"
