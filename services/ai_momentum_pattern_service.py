"""Observe-only AI-style momentum/trend pattern interpretation.

The service summarizes deterministic momentum, trend, regime, microstructure,
and participation facts into a semantic pattern label. It is deliberately
non-authoritative: it cannot approve, reject, size, or alter execution.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Callable


AI_MOMENTUM_PATTERN_VERSION = "ai_momentum_pattern_v2"
AI_MOMENTUM_PATTERN_AUTHORITY = "observe_only_no_live_authority"

Provider = Callable[[str], dict[str, Any] | str]


@dataclass(frozen=True)
class AIMomentumPatternConfig:
    enabled: bool = False
    provider_name: str = "deterministic"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _safe_str(value: Any, default: str = "unknown", max_len: int = 300) -> str:
    text = str(value if value is not None else default).strip()
    if not text:
        text = default
    return text[:max_len]


def _safe_float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _as_list(value: Any, *, max_items: int = 8) -> list[str]:
    if value is None:
        return []
    raw = value if isinstance(value, list) else [value]
    out = []
    for item in raw:
        text = str(item).strip()
        if text and text not in out:
            out.append(text)
        if len(out) >= max_items:
            break
    return out


def build_momentum_pattern_prompt(
    *,
    symbol: str | None,
    action: str | None,
    regime_state: dict[str, Any],
    momentum_state: dict[str, Any],
    trend_state: dict[str, Any],
    event_state: dict[str, Any] | None = None,
) -> str:
    compact = {
        "symbol": symbol,
        "action": action,
        "regime_state": regime_state,
        "momentum_state": momentum_state,
        "trend_state": trend_state,
        "event_state": event_state or {},
    }
    return (
        "Interpret this trading setup's momentum/trend pattern for review "
        "only. Do not approve, reject, size, or recommend an order. Return JSON "
        "only with keys: pattern_label, directional_bias, continuation_assessment, "
        "failure_mode, expected_horizon, favorable_move_probability, "
        "expected_mfe_pct, expected_mae_pct, confidence, missing_evidence, "
        "rationale. Use null for uncalibrated numeric fields.\n\n"
        f"STATE_JSON={json.dumps(compact, sort_keys=True)}"
    )


def _pattern_forecast(
    *,
    pattern_label: str,
    directional_bias: str,
    confidence: str,
) -> dict[str, Any]:
    """Return conservative, explicitly uncalibrated pattern forecast metadata."""
    profile = {
        "trend_continuation_with_participation": {
            "expected_horizon": "15m_to_60m",
            "favorable_move_probability": 0.56,
            "expected_mfe_pct": 0.85,
            "expected_mae_pct": -0.45,
            "holding_time_decay": "moderate_after_60m",
        },
        "late_breakout_liquidity_vacuum": {
            "expected_horizon": "5m_to_30m",
            "favorable_move_probability": 0.43,
            "expected_mfe_pct": 0.35,
            "expected_mae_pct": -0.55,
            "holding_time_decay": "fast",
        },
        "momentum_deterioration": {
            "expected_horizon": "5m_to_30m",
            "favorable_move_probability": 0.38,
            "expected_mfe_pct": 0.25,
            "expected_mae_pct": -0.70,
            "holding_time_decay": "fast_against_long_entries",
        },
        "stretched_momentum_chase": {
            "expected_horizon": "5m_to_30m",
            "favorable_move_probability": 0.44,
            "expected_mfe_pct": 0.40,
            "expected_mae_pct": -0.65,
            "holding_time_decay": "fast_if_volume_fades",
        },
        "isolated_move_without_breadth": {
            "expected_horizon": "15m_to_60m",
            "favorable_move_probability": 0.47,
            "expected_mfe_pct": 0.45,
            "expected_mae_pct": -0.55,
            "holding_time_decay": "moderate",
        },
    }.get(
        pattern_label,
        {
            "expected_horizon": "unknown",
            "favorable_move_probability": 0.50,
            "expected_mfe_pct": None,
            "expected_mae_pct": None,
            "holding_time_decay": "unknown",
        },
    )
    confidence_quality = "uncalibrated_prior"
    if directional_bias in {"risk_negative", "caution"} and confidence == "medium":
        confidence_quality = "directional_risk_prior"
    if pattern_label == "trend_continuation_with_participation":
        confidence_quality = "constructive_prior_needs_outcome_calibration"

    return {
        **profile,
        "confidence_quality": confidence_quality,
        "historical_bucket": {
            "sample_size": 0,
            "win_rate": None,
            "avg_mfe_pct": None,
            "avg_mae_pct": None,
            "ev_pct": None,
            "calibration_error": None,
            "status": "needs_lifecycle_outcomes",
        },
        "prediction_layer": {
            "status": "observe_only",
            "promotion_status": "not_ready",
            "promotion_blockers": [
                "requires_sample_size",
                "requires_calibration_error",
                "requires_rolling_window_stability",
            ],
        },
    }


def deterministic_momentum_pattern(
    *,
    symbol: str | None = None,
    action: str | None = None,
    regime_state: dict[str, Any] | None = None,
    momentum_state: dict[str, Any] | None = None,
    trend_state: dict[str, Any] | None = None,
    event_state: dict[str, Any] | None = None,
) -> dict[str, Any]:
    regime_state = _dict(regime_state)
    momentum_state = _dict(momentum_state)
    trend_state = _dict(trend_state)
    event_state = _dict(event_state)

    trend_direction = _safe_str(trend_state.get("direction"), default="neutral")
    trend_strength = _safe_str(trend_state.get("strength"), default="unknown")
    momentum_label = _safe_str(momentum_state.get("state"), default="unknown")
    session_label = _safe_str(momentum_state.get("session_label"), default="unknown")
    volume_state = _safe_str(momentum_state.get("volume_state"), default="unknown")
    session_phase = _safe_str(regime_state.get("session_phase"), default="unknown")
    breakout_quality = _safe_str(regime_state.get("breakout_quality"), default="unknown")
    vwap_state = _safe_str(regime_state.get("vwap_state"), default="unknown")
    participation = _safe_str(regime_state.get("participation_state"), default="unknown")
    volatility_stretch = _safe_str(regime_state.get("volatility_stretch_state"), default="unknown")
    liquidity = _safe_str(regime_state.get("microstructure_liquidity_state"), default="unknown")

    missing = []
    if trend_direction == "neutral" or trend_strength == "unknown":
        missing.append("confirmed_trend")
    if volume_state == "unknown":
        missing.append("volume_state")
    if participation == "unknown":
        missing.append("participation_confirmation")
    if vwap_state == "unknown":
        missing.append("vwap_state")

    pattern = "mixed_or_unclassified_pattern"
    directional_bias = "neutral"
    continuation = "unclear"
    failure_mode = "insufficient_confluence"
    confidence = "low"

    if (
        trend_direction == "bullish"
        and trend_strength in {"confirmed", "developing"}
        and momentum_label == "accelerating"
        and session_label in {"strong_uptrend", "developing_uptrend"}
        and volume_state in {"surge", "elevated"}
    ):
        pattern = "trend_continuation_with_participation"
        directional_bias = "constructive"
        continuation = "higher_probability_continuation"
        failure_mode = "momentum_deceleration_or_vwap_loss"
        confidence = "medium"

    if (
        breakout_quality in {"weak_breakout", "liquidity_vacuum_breakout"}
        or (session_phase in {"midday", "lunch"} and volume_state in {"thin", "normal"})
    ):
        pattern = "late_breakout_liquidity_vacuum"
        directional_bias = "caution"
        continuation = "fragile_continuation"
        failure_mode = "false_breakout_after_liquidity_decay"
        confidence = "medium"

    if (
        momentum_label == "decelerating"
        or session_label in {"fading", "downtrend"}
        or vwap_state in {"below_vwap", "lost_vwap"}
    ):
        pattern = "momentum_deterioration"
        directional_bias = "risk_negative"
        continuation = "continuation_risk_elevated"
        failure_mode = "failed_follow_through_or_vwap_rejection"
        confidence = "medium"

    if volatility_stretch in {"extreme", "overextended"}:
        pattern = "stretched_momentum_chase"
        directional_bias = "caution"
        continuation = "mean_reversion_risk_elevated"
        failure_mode = "extension_reversal"
        confidence = "medium"

    if participation in {"isolated", "weak", "not_confirmed"}:
        if directional_bias == "constructive":
            directional_bias = "mixed"
        pattern = "isolated_move_without_breadth"
        continuation = "confirmation_needed"
        failure_mode = "peer_or_index_non_confirmation"

    if liquidity in {"thin", "liquidity_thin"} and directional_bias == "constructive":
        directional_bias = "mixed"
        failure_mode = "spread_or_liquidity_absorbs_edge"

    rationale = [
        f"trend={trend_direction}/{trend_strength}",
        f"momentum={momentum_label}",
        f"session={session_label}",
        f"volume={volume_state}",
        f"vwap={vwap_state}",
        f"participation={participation}",
    ]
    event_alignment = event_state.get("ai_market_alignment") or event_state.get("intent_directions")
    if event_alignment:
        rationale.append(f"event_alignment={event_alignment}")
    forecast = _pattern_forecast(
        pattern_label=pattern,
        directional_bias=directional_bias,
        confidence=confidence,
    )

    return {
        "version": AI_MOMENTUM_PATTERN_VERSION,
        "provider": "deterministic_fallback",
        "runtime_effect": "observe_only_no_live_authority",
        "authority": AI_MOMENTUM_PATTERN_AUTHORITY,
        "symbol": symbol,
        "action": action,
        "pattern_label": pattern,
        "directional_bias": directional_bias,
        "continuation_assessment": continuation,
        "failure_mode": failure_mode,
        "expected_horizon": forecast["expected_horizon"],
        "favorable_move_probability": forecast["favorable_move_probability"],
        "expected_mfe_pct": forecast["expected_mfe_pct"],
        "expected_mae_pct": forecast["expected_mae_pct"],
        "holding_time_decay": forecast["holding_time_decay"],
        "confidence_quality": forecast["confidence_quality"],
        "historical_bucket": forecast["historical_bucket"],
        "prediction_layer": forecast["prediction_layer"],
        "confidence": confidence,
        "missing_evidence": missing,
        "rationale": rationale,
    }


def _load_payload(payload: dict[str, Any] | str) -> dict[str, Any]:
    if isinstance(payload, dict):
        return payload
    try:
        loaded = json.loads(str(payload))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def normalize_ai_momentum_pattern(
    fallback: dict[str, Any],
    payload: dict[str, Any] | str,
    *,
    provider_name: str,
) -> dict[str, Any]:
    raw = _load_payload(payload)
    if not raw:
        out = dict(fallback)
        out["provider"] = f"{provider_name}_empty_fallback"
        return out

    rationale = _as_list(raw.get("rationale") or fallback.get("rationale"))
    rationale.append("ai_pattern_observe_only")
    pattern_label = _safe_str(raw.get("pattern_label") or fallback.get("pattern_label"))
    directional_bias = _safe_str(raw.get("directional_bias") or fallback.get("directional_bias"))
    confidence = _safe_str(raw.get("confidence") or fallback.get("confidence"))
    forecast = _pattern_forecast(
        pattern_label=pattern_label,
        directional_bias=directional_bias,
        confidence=confidence,
    )
    historical_bucket = _dict(raw.get("historical_bucket")) or _dict(fallback.get("historical_bucket"))
    if not historical_bucket:
        historical_bucket = forecast["historical_bucket"]
    historical_bucket["status"] = _safe_str(
        historical_bucket.get("status"),
        default="needs_lifecycle_outcomes",
    )
    return {
        "version": AI_MOMENTUM_PATTERN_VERSION,
        "provider": provider_name,
        "runtime_effect": "observe_only_no_live_authority",
        "authority": AI_MOMENTUM_PATTERN_AUTHORITY,
        "symbol": fallback.get("symbol"),
        "action": fallback.get("action"),
        "pattern_label": pattern_label,
        "directional_bias": directional_bias,
        "continuation_assessment": _safe_str(
            raw.get("continuation_assessment") or fallback.get("continuation_assessment")
        ),
        "failure_mode": _safe_str(raw.get("failure_mode") or fallback.get("failure_mode")),
        "expected_horizon": _safe_str(
            raw.get("expected_horizon") or fallback.get("expected_horizon") or forecast["expected_horizon"]
        ),
        "favorable_move_probability": (
            _safe_float(raw.get("favorable_move_probability"))
            if _safe_float(raw.get("favorable_move_probability")) is not None
            else fallback.get("favorable_move_probability", forecast["favorable_move_probability"])
        ),
        "expected_mfe_pct": (
            _safe_float(raw.get("expected_mfe_pct"))
            if _safe_float(raw.get("expected_mfe_pct")) is not None
            else fallback.get("expected_mfe_pct", forecast["expected_mfe_pct"])
        ),
        "expected_mae_pct": (
            _safe_float(raw.get("expected_mae_pct"))
            if _safe_float(raw.get("expected_mae_pct")) is not None
            else fallback.get("expected_mae_pct", forecast["expected_mae_pct"])
        ),
        "holding_time_decay": _safe_str(
            raw.get("holding_time_decay") or fallback.get("holding_time_decay") or forecast["holding_time_decay"]
        ),
        "confidence": confidence,
        "confidence_quality": _safe_str(
            raw.get("confidence_quality")
            or fallback.get("confidence_quality")
            or forecast["confidence_quality"],
        ),
        "historical_bucket": historical_bucket,
        "prediction_layer": {
            **forecast["prediction_layer"],
            **_dict(fallback.get("prediction_layer")),
            **_dict(raw.get("prediction_layer")),
            "status": "observe_only",
        },
        "missing_evidence": _as_list(raw.get("missing_evidence") or fallback.get("missing_evidence")),
        "rationale": rationale,
    }


class AIMomentumPatternService:
    def __init__(
        self,
        *,
        config: AIMomentumPatternConfig | None = None,
        provider: Provider | None = None,
    ):
        self.config = config or AIMomentumPatternConfig()
        self.provider = provider

    def interpret(
        self,
        *,
        symbol: str | None = None,
        action: str | None = None,
        regime_state: dict[str, Any] | None = None,
        momentum_state: dict[str, Any] | None = None,
        trend_state: dict[str, Any] | None = None,
        event_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        fallback = deterministic_momentum_pattern(
            symbol=symbol,
            action=action,
            regime_state=regime_state,
            momentum_state=momentum_state,
            trend_state=trend_state,
            event_state=event_state,
        )
        if not self.config.enabled or self.provider is None:
            if (
                self.config.enabled
                and self.provider is None
                and self.config.provider_name != "deterministic"
            ):
                fallback["provider"] = "enabled_without_provider_fallback"
            return fallback

        prompt = build_momentum_pattern_prompt(
            symbol=symbol,
            action=action,
            regime_state=_dict(regime_state),
            momentum_state=_dict(momentum_state),
            trend_state=_dict(trend_state),
            event_state=_dict(event_state),
        )
        try:
            payload = self.provider(prompt)
            return normalize_ai_momentum_pattern(
                fallback,
                payload,
                provider_name=self.config.provider_name,
            )
        except Exception as exc:
            fallback["provider"] = f"{self.config.provider_name}_error_fallback"
            fallback["provider_error"] = str(exc)[:240]
            return fallback
