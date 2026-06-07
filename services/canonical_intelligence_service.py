"""Canonical per-decision intelligence state snapshot construction."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any

from services.analytics_method_service import build_analytics_method_state
from services.ai_momentum_pattern_service import AI_MOMENTUM_PATTERN_VERSION
from services.confidence_calibration_service import build_calibrated_confidence


CANONICAL_INTELLIGENCE_VERSION = "canonical_intelligence_v1"
CANONICAL_INTELLIGENCE_REQUIRED_SECTIONS = (
    "regime_state",
    "momentum_state",
    "trend_state",
    "event_state",
    "prediction_state",
    "pattern_state",
    "setup_state",
    "strategy_state",
    "opportunity_state",
    "advisory_authority_state",
    "analytics_state",
    "policy_artifact_ref",
    "source_timestamps",
    "freshness_sec",
    "confidence",
)
CANONICAL_INTELLIGENCE_MAX_JSON_BYTES = 19_456


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize(value.get(key)) for key in sorted(value)}
    if isinstance(value, tuple):
        value = list(value)
    if isinstance(value, list):
        normalized = [_normalize(item) for item in value]
        if all(item is None or isinstance(item, (str, int, float, bool)) for item in normalized):
            return sorted(normalized, key=lambda item: (str(type(item)), str(item)))
        return normalized
    if isinstance(value, float):
        return round(value, 10)
    return value


def _json(value: Any) -> str:
    return json.dumps(_normalize(value or {}), sort_keys=True, default=str, separators=(",", ":"))


def _hash(value: dict[str, Any]) -> str:
    return hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def stable_canonical_json(value: Any) -> str:
    """Return deterministic compact JSON for canonical audit payloads."""
    return _json(value)


def stable_canonical_hash(value: dict[str, Any]) -> str:
    """Return a deterministic SHA-256 hash for canonical audit payloads."""
    return _hash(value)


def canonical_json(snapshot: "CanonicalIntelligenceSnapshot") -> str:
    return _json(snapshot.to_dict())


def canonical_json_size_bytes(snapshot: "CanonicalIntelligenceSnapshot") -> int:
    return len(canonical_json(snapshot).encode("utf-8"))


def validate_canonical_snapshot_contract(snapshot: "CanonicalIntelligenceSnapshot") -> dict[str, Any]:
    data = snapshot.to_dict()
    missing_sections = [
        section
        for section in CANONICAL_INTELLIGENCE_REQUIRED_SECTIONS
        if section not in data or not isinstance(data.get(section), dict)
    ]
    size_bytes = canonical_json_size_bytes(snapshot)
    return {
        "ok": not missing_sections and size_bytes <= CANONICAL_INTELLIGENCE_MAX_JSON_BYTES,
        "version": snapshot.version,
        "missing_sections": missing_sections,
        "json_size_bytes": size_bytes,
        "max_json_size_bytes": CANONICAL_INTELLIGENCE_MAX_JSON_BYTES,
        "stable_hash": snapshot.feature_vector_hash,
    }


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _age_seconds(decision_ts: str | None, source_ts: Any) -> float | None:
    decision_dt = _parse_time(decision_ts)
    source_dt = _parse_time(source_ts)
    if not decision_dt or not source_dt:
        return None
    return round((decision_dt - source_dt).total_seconds(), 3)


def _bucket_execution_spread(spread_pct: Any, net_cost_pct: Any) -> str:
    try:
        spread = float(spread_pct)
    except Exception:
        spread = None
    try:
        net_cost = float(net_cost_pct)
    except Exception:
        net_cost = None

    if spread is not None:
        if spread <= 0.05:
            return "tight"
        if spread <= 0.20:
            return "moderate"
        return "wide"
    if net_cost is not None:
        if net_cost <= 0.10:
            return "tight"
        if net_cost <= 0.35:
            return "moderate"
        return "wide"
    return "unknown"


@dataclass(frozen=True)
class CanonicalIntelligenceSnapshot:
    version: str
    symbol: str | None
    decision_ts: str | None
    action: str | None
    feature_semantic_version: str
    regime_state: dict[str, Any]
    momentum_state: dict[str, Any]
    trend_state: dict[str, Any]
    event_state: dict[str, Any]
    prediction_state: dict[str, Any]
    pattern_state: dict[str, Any]
    setup_state: dict[str, Any]
    strategy_state: dict[str, Any]
    opportunity_state: dict[str, Any]
    advisory_authority_state: dict[str, Any]
    analytics_state: dict[str, Any]
    policy_artifact_ref: dict[str, Any]
    source_timestamps: dict[str, Any]
    freshness_sec: dict[str, Any]
    confidence: dict[str, Any]
    feature_vector_hash: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def build_canonical_intelligence_snapshot(
    *,
    symbol: str | None,
    decision_ts: str | None,
    action: str | None,
    context: dict[str, Any],
    account_state: dict[str, Any],
    feature_semantic_version: str,
    market_context_metadata: dict[str, Any] | None = None,
) -> CanonicalIntelligenceSnapshot:
    market_meta = market_context_metadata or {}
    momentum = account_state.get("momentum") or {}
    session = account_state.get("session_momentum") or {}
    prediction = account_state.get("prediction_gate") or {}
    setup = account_state.get("setup_observation") or {}
    setup_quality = account_state.get("setup_quality") or setup.get("setup_quality") or {}
    strategy = account_state.get("strategy_observation") or {}
    trader_brain = strategy.get("trader_brain") or {}
    opportunity = account_state.get("buy_opportunity") or {}
    intelligence = account_state.get("intelligence_context") or {}
    summary = intelligence.get("summary") or {}
    market_regime = account_state.get("market_regime") or {}
    market_microstructure = account_state.get("market_microstructure") or {}
    market_participation = account_state.get("market_participation") or {}
    volatility_normalization = account_state.get("volatility_normalization") or {}
    setup_structure = account_state.get("setup_structure") or setup_quality.get("structure") or {}
    downside_asymmetry = account_state.get("downside_asymmetry") or {}
    exit_decision_quality = account_state.get("exit_decision_quality") or {}
    portfolio_decision = account_state.get("portfolio_decision") or {}
    execution_quality = account_state.get("execution_quality") or {}
    rollout_contract = account_state.get("rollout_contract") or {}
    regime_observation = account_state.get("regime_observation") or {}
    regime_routing_decision = account_state.get("regime_routing_decision") or {}
    regime_observation_context = account_state.get("regime_observation_context") or {}
    spread_bucket = _bucket_execution_spread(
        execution_quality.get("spread_pct"),
        execution_quality.get("net_execution_cost_pct"),
    )

    regime_state = {
        "macro_regime": context.get("macro_regime"),
        "inferred_regime_id": regime_observation.get("regime_id"),
        "inferred_regime_label": regime_observation.get("regime_label"),
        "inferred_regime_confidence": regime_observation.get("confidence"),
        "inferred_regime_stable": regime_observation.get("stable"),
        "inferred_regime_source": regime_observation_context.get(
            "regime_observation_source"
        ),
        "regime_model_slot": regime_routing_decision.get("active_model_slot"),
        "regime_sub_model_strategy": regime_routing_decision.get(
            "sub_model_strategy"
        ),
        "regime_routing_size_modifier": regime_routing_decision.get(
            "size_modifier"
        ),
        "regime_routing_allow_new_longs": regime_routing_decision.get(
            "allow_new_longs"
        ),
        "market_regime": market_regime.get("composite_regime"),
        "trend_regime": market_regime.get("trend_regime"),
        "volatility_regime": market_regime.get("volatility_regime"),
        "event_regime": market_regime.get("event_regime"),
        "sector_rotation_regime": market_regime.get("sector_rotation_regime"),
        "liquidity_regime": market_regime.get("liquidity_regime"),
        "regime_confidence": market_regime.get("confidence"),
        "strategy_weights": market_regime.get("strategy_weights") or {},
        "session_phase": market_microstructure.get("session_phase"),
        "opening_range_state": market_microstructure.get("opening_range_state"),
        "gap_state": market_microstructure.get("gap_state"),
        "vwap_state": market_microstructure.get("vwap_state"),
        "microstructure_liquidity_state": market_microstructure.get("liquidity_state"),
        "intraday_volatility_state": market_microstructure.get("intraday_volatility_state"),
        "compression_state": market_microstructure.get("compression_state"),
        "auction_quality": market_microstructure.get("auction_quality"),
        "breakout_quality": market_microstructure.get("breakout_quality"),
        "reversion_risk": market_microstructure.get("reversion_risk"),
        "microstructure_score": market_microstructure.get("microstructure_score"),
        "microstructure_expectancy_modifier": market_microstructure.get(
            "expectancy_modifier"
        ),
        "participation_state": market_participation.get("participation_state"),
        "sector_relative_strength_state": market_participation.get(
            "sector_relative_strength_state"
        ),
        "peer_confirmation_state": market_participation.get("peer_confirmation_state"),
        "breadth_state": market_participation.get("breadth_state"),
        "index_participation_state": market_participation.get(
            "index_participation_state"
        ),
        "leader_laggard_state": market_participation.get("leader_laggard_state"),
        "relative_volume_state": market_participation.get("relative_volume_state"),
        "participation_confirmation_score": market_participation.get(
            "confirmation_score"
        ),
        "isolated_move_risk": market_participation.get("isolated_move_risk"),
        "participation_expectancy_modifier": market_participation.get(
            "expectancy_modifier"
        ),
        "volatility_stretch_state": volatility_normalization.get("stretch_state"),
        "entry_distance_atr": volatility_normalization.get("entry_distance_atr"),
        "move_zscore": volatility_normalization.get("move_zscore"),
        "range_percentile": volatility_normalization.get("range_percentile"),
        "gap_percentile": volatility_normalization.get("gap_percentile"),
        "spread_atr_pct": volatility_normalization.get("spread_atr_pct"),
        "stop_excursion_ratio": volatility_normalization.get("stop_excursion_ratio"),
        "volatility_normalized_regime": volatility_normalization.get(
            "volatility_regime"
        ),
        "volatility_chase_risk": volatility_normalization.get("chase_risk"),
        "stop_quality": volatility_normalization.get("stop_quality"),
        "volatility_adjusted_score": volatility_normalization.get(
            "volatility_adjusted_score"
        ),
        "volatility_expectancy_modifier": volatility_normalization.get(
            "expectancy_modifier"
        ),
        "downside_state": downside_asymmetry.get("downside_state"),
        "gap_down_vulnerability": downside_asymmetry.get("gap_down_vulnerability"),
        "catalyst_risk": downside_asymmetry.get("catalyst_risk"),
        "overnight_risk": downside_asymmetry.get("overnight_risk"),
        "headline_sensitivity": downside_asymmetry.get("headline_sensitivity"),
        "beta_shock_sensitivity": downside_asymmetry.get("beta_shock_sensitivity"),
        "historical_mae_state": downside_asymmetry.get("historical_mae_state"),
        "failure_signature": downside_asymmetry.get("failure_signature"),
        "downside_score": downside_asymmetry.get("downside_score"),
        "expected_adverse_modifier": downside_asymmetry.get(
            "expected_adverse_modifier"
        ),
        "exit_pressure_state": exit_decision_quality.get("exit_pressure_state"),
        "exit_quality_score": exit_decision_quality.get("exit_quality_score"),
        "exit_recommended_action": exit_decision_quality.get("recommended_action"),
        "risk_multiplier": context.get("risk_multiplier"),
        "market_bias": context.get("market_bias"),
        "market_bias_effective": context.get("market_bias_effective"),
        "market_bias_override_reason": context.get("market_bias_override_reason"),
        "risk_level": context.get("risk_level"),
        "entry_quality": context.get("entry_quality"),
        "portfolio_decision": portfolio_decision.get("decision"),
        "portfolio_size_multiplier": portfolio_decision.get("size_multiplier"),
        "portfolio_duplicate_risk_score": portfolio_decision.get("duplicate_risk_score"),
        "incremental_var_pct": portfolio_decision.get("incremental_var_pct"),
        "beta_contribution_delta": portfolio_decision.get("beta_contribution_delta"),
        "crowded_theme": portfolio_decision.get("crowded_theme"),
        "overlap_symbols": portfolio_decision.get("overlap_symbols") or [],
        "execution_quality_decision": execution_quality.get("decision"),
        "fill_quality": execution_quality.get("fill_quality"),
        "spread_bucket": spread_bucket,
        "spread_pct": execution_quality.get("spread_pct"),
        "slippage_estimate_pct": execution_quality.get("slippage_estimate_pct"),
        "signal_executable_gap_pct": execution_quality.get("signal_executable_gap_pct"),
        "quote_instability_score": execution_quality.get("quote_instability_score"),
        "net_execution_cost_pct": execution_quality.get("net_execution_cost_pct"),
    }
    trend_state = {
        "direction": context.get("trend_direction"),
        "strength": context.get("trend_strength"),
        "correlation_cluster": context.get("correlation_cluster"),
        "cluster_exposure_pct": context.get("cluster_exposure_pct"),
    }
    momentum_state = {
        "direction": context.get("momentum_direction"),
        "momentum_pct": context.get("momentum_pct"),
        "acceleration_pct": context.get("momentum_acceleration_pct"),
        "state": context.get("momentum_state"),
        "volume_surge_ratio": context.get("volume_surge_ratio"),
        "volume_state": context.get("volume_state"),
        "session_label": context.get("session_trend_label"),
        "session_score": context.get("session_trend_score"),
        "session_return_pct": context.get("session_return_pct"),
        "session_momentum_5m_pct": context.get("session_momentum_5m_pct"),
        "session_momentum_15m_pct": context.get("session_momentum_15m_pct"),
        "session_momentum_30m_pct": context.get("session_momentum_30m_pct"),
        "session_momentum_60m_pct": context.get("session_momentum_60m_pct"),
        "session_momentum_120m_pct": context.get("session_momentum_120m_pct"),
        "session_distance_from_vwap_pct": context.get("session_distance_from_vwap_pct"),
        "session_trend_regime": context.get("session_trend_regime"),
        "trend_persistence_score": context.get("trend_persistence_score"),
        "pullback_with_trend_score": context.get("pullback_with_trend_score"),
        "late_chase_maturity_score": context.get("late_chase_maturity_score"),
        "reversal_attempt_score": context.get("reversal_attempt_score"),
    }
    prediction_state = {
        "deterministic_score": prediction.get("prediction_score"),
        "deterministic_decision": prediction.get("prediction_decision"),
        "deterministic_reason": prediction.get("prediction_reason"),
        "ml_score": prediction.get("ml_prediction_score"),
        "ml_bucket": prediction.get("ml_prediction_bucket"),
        "ml_confidence": prediction.get("ml_prediction_confidence"),
        "ml_sample_size": prediction.get("ml_prediction_sample_size"),
        "ml_provider": prediction.get("ml_prediction_provider"),
        "ml_prediction_generated_at": prediction.get("ml_prediction_generated_at"),
        "runtime_effect": prediction.get("ml_prediction_runtime_effect"),
    }
    setup_state = {
        "label": setup.get("setup_label"),
        "policy_action": setup.get("setup_policy_action"),
        "policy_reason": setup.get("setup_policy_reason"),
        "score": setup.get("setup_score"),
        "confidence": setup.get("setup_confidence"),
        "unknown_reason": setup.get("setup_unknown_reason"),
        "quality_source": setup_quality.get("source"),
        "quality_recommendation": setup_quality.get("recommendation"),
        "quality_key": setup_quality.get("key"),
        "structure_state": setup_structure.get("structure_state"),
        "base_quality": setup_structure.get("base_quality"),
        "failed_breakout_risk": setup_structure.get("failed_breakout_risk"),
        "compression_expansion_state": setup_structure.get(
            "compression_expansion_state"
        ),
        "htf_location_state": setup_structure.get("htf_location_state"),
        "anchored_vwap_state": setup_structure.get("anchored_vwap_state"),
        "gap_context_state": setup_structure.get("gap_context_state"),
        "retest_quality": setup_structure.get("retest_quality"),
        "reward_risk_state": setup_structure.get("reward_risk_state"),
        "structure_score": setup_structure.get("structure_score"),
    }
    event_context = account_state.get("event_context") or {}
    event_state = {
        "support_count": summary.get("support_count"),
        "risk_count": summary.get("risk_count"),
        "primary_supports": summary.get("primary_supports"),
        "primary_risks": summary.get("primary_risks"),
        "available": event_context.get("available"),
        "event_signal": event_context.get("event_signal"),
        "authority": event_context.get("authority"),
        "event_count": event_context.get("event_count"),
        "source_count": event_context.get("source_count"),
        "trusted_source_count": event_context.get("trusted_source_count"),
        "confidence_cap": event_context.get("confidence_cap"),
        "source_tiers": event_context.get("source_tiers"),
        "intent_directions": event_context.get("intent_directions"),
        "intent_categories": event_context.get("intent_categories"),
        "intent_scopes": event_context.get("intent_scopes"),
        "confirmation_statuses": event_context.get("confirmation_statuses"),
        "missing_evidence": event_context.get("missing_evidence"),
        "direct_event_count": event_context.get("direct_event_count"),
        "linked_context_event_count": event_context.get("linked_context_event_count"),
        "linked_context_symbols": event_context.get("linked_context_symbols"),
        "ai_interpretation_count": event_context.get("ai_interpretation_count"),
        "ai_event_context_version": event_context.get("ai_event_context_version"),
        "ai_providers": event_context.get("ai_providers"),
        "ai_intents": event_context.get("ai_intents"),
        "ai_market_alignment": event_context.get("ai_market_alignment"),
        "ai_summaries": event_context.get("ai_summaries"),
        "event_intent_version": event_context.get("event_intent_version"),
        "catalyst_score": event_context.get("catalyst_score"),
        "consumer_appetite_score": event_context.get("consumer_appetite_score"),
        "revenue_impact_score": event_context.get("revenue_impact_score"),
        "profit_potential_score": event_context.get("profit_potential_score"),
        "margin_risk_score": event_context.get("margin_risk_score"),
        "supply_chain_risk_score": event_context.get("supply_chain_risk_score"),
        "materials_risk_score": event_context.get("materials_risk_score"),
        "competitive_risk_score": event_context.get("competitive_risk_score"),
        "execution_risk_score": event_context.get("execution_risk_score"),
    }
    strategy_state = {
        "trader_brain_score": trader_brain.get("score"),
        "trader_brain_setup_type": trader_brain.get("setup_type"),
        "approved_by_scorer": trader_brain.get("approved_by_scorer"),
        "reason": trader_brain.get("reason"),
    }
    opportunity_state = {
        "score": opportunity.get("buy_opportunity_score"),
        "recommendation": opportunity.get("buy_opportunity_recommendation"),
        "reason": opportunity.get("buy_opportunity_reason"),
    }
    advisory_authority_state = {
        "decision_policy_outcome": account_state.get("decision_policy_outcome") or {},
        "session_gate_outcome": account_state.get("session_gate_outcome") or {},
        "setup_quality_outcome": account_state.get("setup_quality_outcome") or {},
        "ml_outcome": account_state.get("ml_outcome") or {},
        "paper_learning_authority_outcome": (
            account_state.get("paper_learning_authority_override") or {}
        ),
        "utility_estimate": (
            account_state.get("utility_estimate")
            or (account_state.get("decision_policy") or {}).get("utility_estimate")
            or {}
        ),
        "portfolio_decision": portfolio_decision,
        "execution_quality": execution_quality,
        "regime_observation": regime_observation,
        "regime_routing_decision": regime_routing_decision,
        "market_microstructure": market_microstructure,
        "market_participation": market_participation,
        "volatility_normalization": volatility_normalization,
        "downside_asymmetry": downside_asymmetry,
        "exit_decision_quality": exit_decision_quality,
        "rollout_contract": rollout_contract,
    }
    source_timestamps = {
        "decision_ts": decision_ts,
        "market_context_mtime": market_meta.get("market_context_mtime"),
        "session_momentum_updated_at": session.get("updated_at"),
        "latest_bar_timestamp": (
            (account_state.get("tape") or {}).get("latest_bar_timestamp")
            or momentum.get("latest_bar_timestamp")
        ),
    }
    freshness_sec = {
        "market_context": _age_seconds(decision_ts, market_meta.get("market_context_mtime")),
        "session_momentum": _age_seconds(decision_ts, session.get("updated_at")),
        "tape_bar_age": context.get("tape_bar_age_seconds"),
    }
    confidence = {
        "decision_confidence_hint": account_state.get("signal_confidence_hint"),
        "setup_confidence": setup.get("setup_confidence"),
        "prediction_confidence": prediction.get("ml_prediction_confidence"),
        "market_context_confidence": context.get("market_bias"),
    }
    policy_artifact_ref = (
        account_state.get("policy_artifacts")
        or account_state.get("policy_artifact_status")
        or {}
    )
    calibrated_confidence = (
        account_state.get("calibrated_confidence")
        or build_calibrated_confidence(
            account_state=account_state,
            context=context,
        ).to_dict()
    )
    confidence_payload = {
        "raw_confidence_labels": confidence,
        "calibrated_confidence": calibrated_confidence,
        "primary_source": calibrated_confidence.get("primary_source"),
        "primary_predicted_win_rate": calibrated_confidence.get(
            "primary_predicted_win_rate"
        ),
        "primary_realized_win_rate": calibrated_confidence.get(
            "primary_realized_win_rate"
        ),
        "confidence_quality": calibrated_confidence.get("confidence_quality"),
    }
    analytics_state = build_analytics_method_state(
        symbol=symbol,
        context=context,
        account_state=account_state,
    )
    ai_pattern = analytics_state.get("ai_momentum_pattern") or {}
    historical_bar_model = analytics_state.get("historical_bar_model_intelligence") or {}
    historical_bar_paper = analytics_state.get("historical_bar_paper_strategy") or {}
    analytics_families = analytics_state.get("families") or {}
    historical_bar_family = analytics_families.get("historical_bar_ml") or {}
    paper_strategy_family = analytics_families.get("paper_strategy_ensemble") or {}
    prediction_layer = ai_pattern.get("prediction_layer") or {}
    pattern_state = {
        "version": ai_pattern.get("version") or AI_MOMENTUM_PATTERN_VERSION,
        "runtime_effect": (
            ai_pattern.get("runtime_effect")
            or "observe_only_no_live_authority"
        ),
        "pattern_label": ai_pattern.get("pattern_label"),
        "directional_bias": ai_pattern.get("directional_bias"),
        "failure_mode": ai_pattern.get("failure_mode"),
        "expected_horizon": ai_pattern.get("expected_horizon"),
        "favorable_move_probability": ai_pattern.get(
            "favorable_move_probability"
        ),
        "expected_mfe_pct": ai_pattern.get("expected_mfe_pct"),
        "expected_mae_pct": ai_pattern.get("expected_mae_pct"),
        "confidence": ai_pattern.get("confidence"),
        "confidence_quality": ai_pattern.get("confidence_quality"),
        "historical_sample_size": ai_pattern.get("historical_sample_size"),
        "historical_status": ai_pattern.get("historical_status"),
        "prediction_status": prediction_layer.get("status"),
        "historical_bar_model_status": historical_bar_model.get("status"),
        "historical_bar_ready_label_count": historical_bar_model.get(
            "ready_label_count"
        ),
        "historical_bar_label_targets": historical_bar_model.get("label_targets") or [],
        "historical_bar_runtime_effect": (
            historical_bar_model.get("runtime_effect")
            or historical_bar_family.get("runtime_effect")
        ),
        "historical_bar_master_confidence_score": historical_bar_paper.get(
            "master_confidence_score"
        ),
        "historical_bar_confidence_bucket": historical_bar_paper.get(
            "confidence_bucket"
        ),
        "historical_bar_paper_recommendation": historical_bar_paper.get(
            "paper_recommendation"
        ),
        "historical_bar_paper_position_size_pct": historical_bar_paper.get(
            "paper_position_size_pct"
        ),
        "historical_bar_baseline_delta": historical_bar_paper.get("baseline_delta"),
        "historical_bar_paper_runtime_effect": (
            historical_bar_paper.get("runtime_effect")
            or paper_strategy_family.get("runtime_effect")
        ),
        "missing_evidence": ai_pattern.get("missing_evidence") or [],
        "provider": ai_pattern.get("provider") or "deterministic_fallback",
        "authority": "observe_only_no_live_authority",
    }

    feature_vector = {
        "regime_state": regime_state,
        "momentum_state": momentum_state,
        "trend_state": trend_state,
        "event_state": event_state,
        "prediction_state": prediction_state,
        "pattern_state": pattern_state,
        "setup_state": setup_state,
        "strategy_state": strategy_state,
        "opportunity_state": opportunity_state,
        "advisory_authority_state": advisory_authority_state,
        "analytics_state": analytics_state,
        "policy_artifact_ref": policy_artifact_ref,
        "source_timestamps": source_timestamps,
        "freshness_sec": freshness_sec,
        "confidence": confidence_payload,
    }

    return CanonicalIntelligenceSnapshot(
        version=CANONICAL_INTELLIGENCE_VERSION,
        symbol=symbol,
        decision_ts=decision_ts,
        action=action,
        feature_semantic_version=feature_semantic_version,
        regime_state=regime_state,
        momentum_state=momentum_state,
        trend_state=trend_state,
        event_state=event_state,
        prediction_state=prediction_state,
        pattern_state=pattern_state,
        setup_state=setup_state,
        strategy_state=strategy_state,
        opportunity_state=opportunity_state,
        advisory_authority_state=advisory_authority_state,
        analytics_state=analytics_state,
        policy_artifact_ref=policy_artifact_ref,
        source_timestamps=source_timestamps,
        freshness_sec=freshness_sec,
        confidence=confidence_payload,
        feature_vector_hash=_hash(feature_vector),
    )
