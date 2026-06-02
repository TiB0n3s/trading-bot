"""Compatibility helpers for historical symbol pattern observations.

New canonical snapshots store ``pattern_state`` directly. Older rows may only
have ``analytics_state.ai_momentum_pattern`` or the lower-level
regime/momentum/trend sections needed to derive the same observe-only bucket.
This module provides read-time backfill without rewriting historical canonical
hashes.
"""

from __future__ import annotations

from typing import Any

from services.ai_momentum_pattern_service import deterministic_momentum_pattern


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def canonical_symbol_pattern_state(canonical: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized observe-only symbol pattern state for one snapshot."""
    canonical = _dict(canonical)
    pattern = _dict(canonical.get("pattern_state"))
    if pattern.get("pattern_label"):
        return {
            **pattern,
            "authority": pattern.get("authority") or "observe_only_no_live_authority",
            "runtime_effect": pattern.get("runtime_effect")
            or "observe_only_no_live_authority",
            "source": pattern.get("source") or "canonical_pattern_state",
        }

    analytics_pattern = _dict(
        _dict(canonical.get("analytics_state")).get("ai_momentum_pattern")
    )
    if analytics_pattern.get("pattern_label"):
        prediction_layer = _dict(analytics_pattern.get("prediction_layer"))
        return {
            "version": analytics_pattern.get("version") or "ai_momentum_pattern_v2",
            "runtime_effect": analytics_pattern.get("runtime_effect")
            or "observe_only_no_live_authority",
            "pattern_label": analytics_pattern.get("pattern_label"),
            "directional_bias": analytics_pattern.get("directional_bias"),
            "failure_mode": analytics_pattern.get("failure_mode"),
            "expected_horizon": analytics_pattern.get("expected_horizon"),
            "favorable_move_probability": analytics_pattern.get(
                "favorable_move_probability"
            ),
            "expected_mfe_pct": analytics_pattern.get("expected_mfe_pct"),
            "expected_mae_pct": analytics_pattern.get("expected_mae_pct"),
            "confidence": analytics_pattern.get("confidence"),
            "confidence_quality": analytics_pattern.get("confidence_quality"),
            "historical_sample_size": analytics_pattern.get(
                "historical_sample_size"
            ),
            "historical_status": analytics_pattern.get("historical_status"),
            "prediction_status": prediction_layer.get("status"),
            "missing_evidence": analytics_pattern.get("missing_evidence") or [],
            "provider": analytics_pattern.get("provider") or "historical_analytics",
            "authority": "observe_only_no_live_authority",
            "source": "analytics_state_ai_momentum_pattern",
        }

    derived = deterministic_momentum_pattern(
        symbol=canonical.get("symbol"),
        action=canonical.get("action"),
        regime_state=_dict(canonical.get("regime_state")),
        momentum_state=_dict(canonical.get("momentum_state")),
        trend_state=_dict(canonical.get("trend_state")),
        event_state=_dict(canonical.get("event_state")),
    )
    prediction_layer = _dict(derived.get("prediction_layer"))
    return {
        "version": derived.get("version") or "ai_momentum_pattern_v2",
        "runtime_effect": derived.get("runtime_effect")
        or "observe_only_no_live_authority",
        "pattern_label": derived.get("pattern_label"),
        "directional_bias": derived.get("directional_bias"),
        "failure_mode": derived.get("failure_mode"),
        "expected_horizon": derived.get("expected_horizon"),
        "favorable_move_probability": derived.get("favorable_move_probability"),
        "expected_mfe_pct": derived.get("expected_mfe_pct"),
        "expected_mae_pct": derived.get("expected_mae_pct"),
        "confidence": derived.get("confidence"),
        "confidence_quality": derived.get("confidence_quality"),
        "historical_sample_size": _dict(derived.get("historical_bucket")).get(
            "sample_size"
        ),
        "historical_status": _dict(derived.get("historical_bucket")).get("status"),
        "prediction_status": prediction_layer.get("status"),
        "missing_evidence": derived.get("missing_evidence") or [],
        "provider": derived.get("provider") or "deterministic_fallback",
        "authority": "observe_only_no_live_authority",
        "source": "derived_from_canonical_sections",
    }
