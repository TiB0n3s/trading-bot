#!/usr/bin/env python3
"""
Market brief schema helpers.

Defines the richer market_context.json shape we want long-term while preserving
backward compatibility with the existing bot fields.

This module is read-only/validation-focused. It does not change trading behavior.
"""

from __future__ import annotations

from typing import Any

VALID_BIAS = {"buy", "avoid", "neutral"}
VALID_CONFIDENCE = {"low", "medium", "high"}
VALID_FUNDAMENTAL = {"strong_bullish", "bullish", "neutral", "bearish", "strong_bearish"}
VALID_RISK = {"low", "medium", "high", "very_high"}
VALID_ENTRY_QUALITY = {
    "excellent",
    "high",
    "good_on_pullbacks",
    "good_if_holds_gap",
    "good_if_breadth_holds",
    "conditional",
    "tactical_only",
    "hedge_only",
    "do_not_chase",
    "avoid_chasing",
    "poor",
}
VALID_AVOID_TYPE = {None, "soft", "hard"}
VALID_MACRO_REGIME = {
    "risk_on",
    "normal",
    "caution",
    "mixed",
    "defensive",
    "risk_off",
    "capital_preservation",
}


LEARNING_ENRICHMENT_FIELDS = (
    "data_snapshot",
    "technical_levels_degraded",
    "technical_levels_source",
    "prior_session_market_date",
    "prior_session_session_return_pct",
    "prior_session_mfe_pct",
    "prior_session_max_favorable_excursion_pct",
    "prior_session_participated",
    "prior_session_participation_quality",
    "prior_session_prediction_score",
    "prior_session_trend_label",
    "prior_session_timing_score",
    "session_momentum_label",
    "session_momentum_score",
    "session_return_pct",
    "session_momentum_5m_pct",
    "session_momentum_15m_pct",
    "session_momentum_30m_pct",
    "session_distance_from_vwap_pct",
    "session_momentum_reason",
    "session_momentum_upgrade",
    "session_momentum_upgrade_reason",
    "prediction_score",
    "prediction_confidence",
    "prediction_expected_pnl",
    "prediction_expected_win_rate",
    "prediction_sample_size",
    "prediction_timing_score",
    "prediction_recommended_entry_timing",
    "prediction_recommended_exit_timing",
    "prediction_trend_score",
    "prediction_trend_label",
    "prediction_trend_regime",
    "prediction_trend_confidence",
    "prediction_reason",
    "strategy_memory_trades",
    "strategy_memory_wins",
    "strategy_memory_losses",
    "strategy_memory_win_rate",
    "strategy_memory_pnl",
    "strategy_memory_expectancy",
    "strategy_memory_avg_pnl_pct",
    "performance_score",
    "performance_label",
    "performance_confidence",
    "performance_reason",
    "performance_evidence",
    "cot_positioning_context",
    "prime_brokerage_context",
    "dealer_gamma_context",
    "webull_morning_brief_context",
    "webull_market_context",
)


def learning_enrichment_fields(entry: dict[str, Any]) -> dict[str, Any]:
    """Preserve optional learning/enrichment fields in market_context symbols."""
    out = {}
    for key in LEARNING_ENRICHMENT_FIELDS:
        if key in entry:
            out[key] = entry.get(key)
    return out


def clamp_score(value: Any, default: int | None = None) -> int | None:
    try:
        v = int(float(value))
    except Exception:
        return default

    return max(0, min(10, v))


def normalize_string(value: Any) -> str | None:
    if not isinstance(value, str):
        return None
    value = value.strip()
    return value or None


def normalize_symbol_entry(symbol: str, entry: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize one symbol entry into the richer schema."""
    entry = entry or {}

    bias = str(entry.get("bias") or entry.get("trading_bias") or "neutral").lower()
    if bias not in VALID_BIAS:
        bias = "neutral"

    confidence = str(entry.get("confidence") or "medium").lower()
    if confidence not in VALID_CONFIDENCE:
        confidence = "medium"

    fundamental = entry.get("fundamental_score")
    if isinstance(fundamental, str):
        fundamental = fundamental.lower().replace(" ", "_")
    if fundamental not in VALID_FUNDAMENTAL:
        fundamental = None

    risk = entry.get("risk_level")
    if isinstance(risk, str):
        risk = risk.lower().replace(" ", "_")
        if risk == "normal":
            risk = "medium"
    if risk not in VALID_RISK:
        risk = None

    entry_quality = entry.get("entry_quality")
    if isinstance(entry_quality, str):
        entry_quality = entry_quality.lower().replace(" ", "_")
    if entry_quality not in VALID_ENTRY_QUALITY:
        entry_quality = None

    avoid_type = entry.get("avoid_type")
    if avoid_type not in VALID_AVOID_TYPE:
        avoid_type = None

    normalized = {
        # Existing live-compatible fields
        "bias": bias,
        "reason": normalize_string(entry.get("reason")) or "no detail provided",
        "confidence": confidence,
        "fundamental_score": fundamental,
        "risk_level": risk,
        "entry_quality": entry_quality,
        "avoid_type": avoid_type,
        # New richer research fields; observe-only for now
        "catalyst_score": clamp_score(entry.get("catalyst_score")),
        "relative_strength_score": clamp_score(entry.get("relative_strength_score")),
        "sector_alignment": normalize_string(entry.get("sector_alignment")),
        "index_alignment": normalize_string(entry.get("index_alignment")),
        "liquidity_quality": normalize_string(entry.get("liquidity_quality")),
        "volume_context": normalize_string(entry.get("volume_context")),
        "price_location": normalize_string(entry.get("price_location")),
        "key_catalysts": entry.get("key_catalysts")
        if isinstance(entry.get("key_catalysts"), list)
        else [],
        "key_risks": entry.get("key_risks") if isinstance(entry.get("key_risks"), list) else [],
        "support_levels": entry.get("support_levels")
        if isinstance(entry.get("support_levels"), list)
        else [],
        "resistance_levels": entry.get("resistance_levels")
        if isinstance(entry.get("resistance_levels"), list)
        else [],
        "notes": normalize_string(entry.get("notes")),
        # Event-enrichment fields; observe-only metadata for reporting/scoring.
        "event_context": entry.get("event_context")
        if isinstance(entry.get("event_context"), dict)
        else None,
        "event_catalyst_score_raw": entry.get("event_catalyst_score_raw"),
        "consumer_appetite_score": entry.get("consumer_appetite_score"),
        "revenue_impact_score": entry.get("revenue_impact_score"),
        "profit_potential_score": entry.get("profit_potential_score"),
        "margin_risk_score": entry.get("margin_risk_score"),
        "supply_chain_risk_score": entry.get("supply_chain_risk_score"),
        "materials_risk_score": entry.get("materials_risk_score"),
        "competitive_risk_score": entry.get("competitive_risk_score"),
        "execution_risk_score": entry.get("execution_risk_score"),
        # Holistic performance context; observe-only metadata distinct from
        # conservative action confidence.
        "performance_score": entry.get("performance_score"),
        "performance_label": normalize_string(entry.get("performance_label")),
        "performance_confidence": normalize_string(entry.get("performance_confidence")),
        "performance_reason": normalize_string(entry.get("performance_reason")),
        "performance_evidence": (
            entry.get("performance_evidence")
            if isinstance(entry.get("performance_evidence"), list)
            else []
        ),
        # Weekly CFTC COT macro-positioning context. This is a context/size
        # modifier only and never standalone trade authority.
        "cot_positioning_context": (
            entry.get("cot_positioning_context")
            if isinstance(entry.get("cot_positioning_context"), dict)
            else None
        ),
        # External prime-brokerage / hedge-fund flow context. This is a
        # context/size modifier only and never standalone trade authority.
        "prime_brokerage_context": (
            entry.get("prime_brokerage_context")
            if isinstance(entry.get("prime_brokerage_context"), dict)
            else None
        ),
        # Options dealer-gamma context. This is volatility-regime and level
        # context only, never standalone trade authority.
        "dealer_gamma_context": (
            entry.get("dealer_gamma_context")
            if isinstance(entry.get("dealer_gamma_context"), dict)
            else None
        ),
        # Webull morning brief context. This is event/attention/technical
        # context only, never standalone trade authority.
        "webull_morning_brief_context": (
            entry.get("webull_morning_brief_context")
            if isinstance(entry.get("webull_morning_brief_context"), dict)
            else None
        ),
        # Webull screener/news/attention evidence. This is context and
        # learning-attribution metadata only, never standalone trade authority.
        "webull_market_context": (
            entry.get("webull_market_context")
            if isinstance(entry.get("webull_market_context"), dict)
            else None
        ),
    }

    normalized.update(learning_enrichment_fields(entry))
    return normalized


def normalize_market_context(
    raw: dict[str, Any], approved_symbols: list[str] | set[str]
) -> dict[str, Any]:
    """Normalize a full market_context-style dict."""
    symbols_raw = raw.get("symbols") or {}

    symbols = {}
    for sym in approved_symbols:
        symbols[sym] = normalize_symbol_entry(sym, symbols_raw.get(sym))

    macro_regime = raw.get("macro_regime")
    if isinstance(macro_regime, str):
        macro_regime = macro_regime.lower().replace("-", "_").replace(" ", "_")
    if macro_regime not in VALID_MACRO_REGIME:
        macro_regime = None

    return {
        "market_date": raw.get("market_date"),
        "generated_at": raw.get("generated_at"),
        "macro_sentiment": raw.get("macro_sentiment"),
        "macro_regime": macro_regime,
        "macro_summary": raw.get("macro_summary"),
        "risk_multiplier": raw.get("risk_multiplier"),
        "max_new_positions": raw.get("max_new_positions"),
        "block_new_buys": raw.get("block_new_buys"),
        # New richer top-level sections
        "index_state": raw.get("index_state") if isinstance(raw.get("index_state"), dict) else {},
        "sector_state": raw.get("sector_state")
        if isinstance(raw.get("sector_state"), dict)
        else {},
        "macro_events": raw.get("macro_events")
        if isinstance(raw.get("macro_events"), list)
        else [],
        # Context quality metadata.
        "data_only": raw.get("data_only"),
        "source_quality": raw.get("source_quality"),
        "event_enrichment_count": raw.get("event_enrichment_count"),
        "intraday_refresh_at": raw.get("intraday_refresh_at"),
        "cot_positioning_context": (
            raw.get("cot_positioning_context")
            if isinstance(raw.get("cot_positioning_context"), dict)
            else None
        ),
        "prime_brokerage_context": (
            raw.get("prime_brokerage_context")
            if isinstance(raw.get("prime_brokerage_context"), dict)
            else None
        ),
        "dealer_gamma_context": (
            raw.get("dealer_gamma_context")
            if isinstance(raw.get("dealer_gamma_context"), dict)
            else None
        ),
        "webull_morning_brief_context": (
            raw.get("webull_morning_brief_context")
            if isinstance(raw.get("webull_morning_brief_context"), dict)
            else None
        ),
        "webull_market_context": (
            raw.get("webull_market_context")
            if isinstance(raw.get("webull_market_context"), dict)
            else None
        ),
        "symbols": symbols,
        "source": raw.get("source"),
        "format": raw.get("format"),
    }


def schema_quality_summary(ctx: dict[str, Any]) -> dict[str, Any]:
    """Return coverage counts for the richer schema."""
    symbols = ctx.get("symbols") or {}

    total = len(symbols)
    rich_fields = [
        "catalyst_score",
        "relative_strength_score",
        "sector_alignment",
        "index_alignment",
        "liquidity_quality",
        "volume_context",
        "price_location",
        "prediction_score",
        "prediction_expected_pnl",
        "strategy_memory_expectancy",
        "session_momentum_label",
        "prior_session_session_return_pct",
        "performance_score",
        "performance_label",
        "performance_confidence",
    ]

    coverage = {}
    for field in rich_fields:
        coverage[field] = sum(
            1
            for entry in symbols.values()
            if isinstance(entry, dict) and entry.get(field) not in (None, "", [])
        )

    return {
        "symbol_count": total,
        "index_state_count": len(ctx.get("index_state") or {}),
        "sector_state_count": len(ctx.get("sector_state") or {}),
        "macro_events_count": len(ctx.get("macro_events") or []),
        "rich_field_coverage": coverage,
    }
