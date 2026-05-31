"""Canonical per-decision intelligence state snapshot construction."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import hashlib
import json
from typing import Any


CANONICAL_INTELLIGENCE_VERSION = "canonical_intelligence_v1"
CANONICAL_INTELLIGENCE_REQUIRED_SECTIONS = (
    "regime_state",
    "momentum_state",
    "trend_state",
    "event_state",
    "prediction_state",
    "setup_state",
    "strategy_state",
    "opportunity_state",
    "advisory_authority_state",
    "policy_artifact_ref",
    "source_timestamps",
    "freshness_sec",
    "confidence",
)
CANONICAL_INTELLIGENCE_MAX_JSON_BYTES = 16_384


def _normalize(value: Any) -> Any:
    if isinstance(value, dict):
        return {key: _normalize(value.get(key)) for key in sorted(value)}
    if isinstance(value, tuple):
        value = list(value)
    if isinstance(value, list):
        return [_normalize(item) for item in value]
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
    setup_state: dict[str, Any]
    strategy_state: dict[str, Any]
    opportunity_state: dict[str, Any]
    advisory_authority_state: dict[str, Any]
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

    regime_state = {
        "macro_regime": context.get("macro_regime"),
        "risk_multiplier": context.get("risk_multiplier"),
        "market_bias": context.get("market_bias"),
        "market_bias_effective": context.get("market_bias_effective"),
        "market_bias_override_reason": context.get("market_bias_override_reason"),
        "risk_level": context.get("risk_level"),
        "entry_quality": context.get("entry_quality"),
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
        "session_distance_from_vwap_pct": context.get("session_distance_from_vwap_pct"),
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
    }
    event_state = {
        "support_count": summary.get("support_count"),
        "risk_count": summary.get("risk_count"),
        "primary_supports": summary.get("primary_supports"),
        "primary_risks": summary.get("primary_risks"),
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

    feature_vector = {
        "regime_state": regime_state,
        "momentum_state": momentum_state,
        "trend_state": trend_state,
        "event_state": event_state,
        "prediction_state": prediction_state,
        "setup_state": setup_state,
        "strategy_state": strategy_state,
        "opportunity_state": opportunity_state,
        "advisory_authority_state": advisory_authority_state,
        "policy_artifact_ref": policy_artifact_ref,
        "source_timestamps": source_timestamps,
        "freshness_sec": freshness_sec,
        "confidence": confidence,
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
        setup_state=setup_state,
        strategy_state=strategy_state,
        opportunity_state=opportunity_state,
        advisory_authority_state=advisory_authority_state,
        policy_artifact_ref=policy_artifact_ref,
        source_timestamps=source_timestamps,
        freshness_sec=freshness_sec,
        confidence=confidence,
        feature_vector_hash=_hash(feature_vector),
    )
