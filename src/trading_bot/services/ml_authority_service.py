from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from services.approval_models import MLAuthorityOutcome
from services.ml_authority_circuit_breaker_service import (
    MLAuthorityCircuitBreaker,
    circuit_config_from,
)

_ML_CONFIDENCE_RANK = {
    None: -1,
    "": -1,
    "unknown": 0,
    "low": 1,
    "medium": 2,
    "high": 3,
}


def _parse_ml_prediction_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        if isinstance(value, (int, float)):
            raw = float(value)
            ts = raw / 1000 if raw > 10_000_000_000 else raw
            return datetime.fromtimestamp(ts, tz=timezone.utc)

        text = str(value).strip()
        if not text:
            return None
        if text.isdigit():
            raw = float(text)
            ts = raw / 1000 if len(text) > 10 else raw
            return datetime.fromtimestamp(ts, tz=timezone.utc)

        parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _ml_prediction_age_seconds(ml_prediction: dict[str, Any]) -> float | None:
    parsed = _parse_ml_prediction_timestamp((ml_prediction or {}).get("prediction_generated_at"))
    if parsed is None:
        return None
    return max(0.0, (datetime.now(timezone.utc) - parsed).total_seconds())


def _float_or_none(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _prediction_health_failure_reason(
    *,
    ml_prediction: dict[str, Any],
    age_seconds: float | None,
    max_age_seconds: int,
    model_fallback_required: bool,
) -> str | None:
    status_values = {
        str(ml_prediction.get(key) or "").strip().lower()
        for key in (
            "status",
            "prediction_status",
            "model_status",
            "health",
            "cache_status",
        )
    }
    failed_statuses = {
        "failed",
        "failure",
        "error",
        "errored",
        "stale",
        "missing",
        "unavailable",
        "fallback_required",
    }
    failed = sorted(value for value in status_values if value in failed_statuses)
    if failed:
        return f"prediction_status={failed[0]}"
    if model_fallback_required:
        return "model_staleness_guard=fallback_required"
    if max_age_seconds > 0 and age_seconds is None:
        return "prediction_freshness_timestamp_missing"
    if max_age_seconds > 0 and age_seconds is not None and age_seconds > max_age_seconds:
        return f"prediction_stale age={age_seconds:.1f}s max={max_age_seconds}s"
    return None


def _late_chase_entry_risk(
    *,
    account_state: dict[str, Any],
    setup_obs: dict[str, Any],
) -> dict[str, Any]:
    setup_quality = account_state.get("setup_quality") or {}
    rolling = account_state.get("rolling_momentum") or {}
    session = account_state.get("session_momentum") or {}
    momentum = account_state.get("momentum") or {}

    setup_label = (
        setup_quality.get("label") or setup_obs.get("setup_label") or setup_obs.get("label") or ""
    )
    setup_action = setup_quality.get("policy_action") or setup_obs.get("setup_policy_action") or ""
    setup_rec = setup_quality.get("recommendation") or setup_obs.get("recommendation") or ""
    setup_score = _float_or_none(
        setup_quality.get("score") or setup_obs.get("setup_score") or setup_obs.get("score")
    )
    setup_score_value = setup_score if setup_score is not None else 0.0

    special_labels = {
        str(label).lower() for label in (rolling.get("special_labels") or []) if label is not None
    }
    extension_pct = _float_or_none(rolling.get("extension_from_recent_base_pct"))
    vwap_dist_pct = _float_or_none(
        account_state.get("session_distance_from_vwap_pct")
        or session.get("distance_from_vwap_pct")
        or momentum.get("distance_from_vwap_pct")
    )
    session_return_pct = _float_or_none(
        account_state.get("session_return_pct") or session.get("session_return_pct")
    )
    m15_pct = _float_or_none(
        account_state.get("session_momentum_15m_pct") or session.get("momentum_15m_pct")
    )
    m30_pct = _float_or_none(
        account_state.get("session_momentum_30m_pct") or session.get("momentum_30m_pct")
    )
    m60_pct = _float_or_none(
        account_state.get("session_momentum_60m_pct") or session.get("momentum_60m_pct")
    )
    m120_pct = _float_or_none(
        account_state.get("session_momentum_120m_pct") or session.get("momentum_120m_pct")
    )
    maturity_score = _float_or_none(
        account_state.get("late_chase_maturity_score") or session.get("late_chase_maturity_score")
    )

    weak_labels = {
        "above_vwap_neutral_continuation",
        "unclassified_transition",
        "balanced_transition_state",
        "above_vwap_strength_continuation",
        "late_strength_near_vwap_risk",
    }
    weak_setup = (
        str(setup_label).lower() in weak_labels
        or str(setup_action).lower() not in {"boost", "allow"}
        or str(setup_rec).lower() in {"watch", "neutral", "avoid"}
        or setup_score_value < 55
    )
    extended = (
        "gap_up_chase_risk" in special_labels
        or "extended_above_recent_base" in special_labels
        or (extension_pct is not None and extension_pct >= 5.0)
        or (vwap_dist_pct is not None and vwap_dist_pct >= 1.25)
    )
    fading_after_push = (
        (session_return_pct is not None and session_return_pct >= 0.75)
        and (vwap_dist_pct is not None and vwap_dist_pct >= 0.75)
        and (m15_pct is not None and m15_pct <= 0)
        and (m30_pct is not None and m30_pct <= 0)
    )
    extreme_extension = (extension_pct is not None and extension_pct >= 8.0) or (
        vwap_dist_pct is not None and vwap_dist_pct >= 1.75
    )
    mature_long_chase = (maturity_score is not None and maturity_score >= 3) or (
        (m60_pct is not None and m60_pct >= 1.0)
        and (m120_pct is not None and m120_pct >= 1.5)
        and (vwap_dist_pct is not None and vwap_dist_pct >= 1.25)
    )
    triggered = bool(weak_setup and (extended or fading_after_push))
    would_block = bool(triggered and (extreme_extension or fading_after_push or mature_long_chase))

    cap_pct = None
    if triggered:
        cap_pct = 0.35 if extreme_extension or fading_after_push or mature_long_chase else 0.50

    reasons = []
    if weak_setup:
        reasons.append("weak_setup")
    if extended:
        reasons.append("extended")
    if fading_after_push:
        reasons.append("fading_after_push")
    if extreme_extension:
        reasons.append("extreme_extension")
    if mature_long_chase:
        reasons.append("mature_long_chase")

    return {
        "triggered": triggered,
        "would_block": would_block,
        "cap_pct": cap_pct,
        "setup_label": setup_label,
        "setup_action": setup_action,
        "setup_recommendation": setup_rec,
        "setup_score": setup_score,
        "special_labels": sorted(special_labels),
        "extension_from_recent_base_pct": extension_pct,
        "session_distance_from_vwap_pct": vwap_dist_pct,
        "session_return_pct": session_return_pct,
        "session_momentum_15m_pct": m15_pct,
        "session_momentum_30m_pct": m30_pct,
        "session_momentum_60m_pct": m60_pct,
        "session_momentum_120m_pct": m120_pct,
        "late_chase_maturity_score": maturity_score,
        "reason": ",".join(reasons) if reasons else "no late-chase risk",
    }


def _advisory_feature_size_cap(account_state: dict[str, Any]) -> dict[str, Any]:
    micro = account_state.get("market_microstructure") or {}
    participation = account_state.get("market_participation") or {}
    volatility = account_state.get("volatility_normalization") or {}
    downside = account_state.get("downside_asymmetry") or {}

    caps: list[tuple[str, float, str]] = []

    if volatility.get("chase_risk") == "high":
        caps.append(("volatility_normalization", 0.60, "high volatility chase risk"))
    elif volatility.get("chase_risk") == "elevated":
        caps.append(("volatility_normalization", 0.80, "elevated volatility chase risk"))

    if micro.get("reversion_risk") == "high":
        caps.append(("market_microstructure", 0.70, "high microstructure reversion risk"))
    elif micro.get("breakout_quality") == "liquidity_vacuum_breakout":
        caps.append(("market_microstructure", 0.75, "breakout in liquidity vacuum"))

    if (
        participation.get("participation_state") == "isolated_or_weak"
        or participation.get("isolated_move_risk") == "high"
    ):
        caps.append(("market_participation", 0.70, "isolated or weak market participation"))
    elif participation.get("isolated_move_risk") == "elevated":
        caps.append(("market_participation", 0.85, "elevated isolated-move risk"))

    downside_score = _float_or_none(downside.get("downside_score"))
    if downside.get("downside_state") == "asymmetric_downside_high" or (
        downside_score is not None and downside_score >= 0.65
    ):
        caps.append(("downside_asymmetry", 0.70, "high asymmetric downside"))
    elif downside.get("downside_state") == "asymmetric_downside_elevated" or (
        downside_score is not None and downside_score >= 0.42
    ):
        caps.append(("downside_asymmetry", 0.85, "elevated asymmetric downside"))

    if not caps:
        return {
            "triggered": False,
            "effect_on_size": "none",
            "reason": "no advisory feature size cap",
        }

    source, cap_pct, reason = min(caps, key=lambda item: item[1])
    return {
        "triggered": True,
        "effect_on_size": "cap",
        "source": source,
        "cap_pct": cap_pct,
        "reason": reason,
        "all_caps": [{"source": item[0], "cap_pct": item[1], "reason": item[2]} for item in caps],
        "market_microstructure": {
            "breakout_quality": micro.get("breakout_quality"),
            "reversion_risk": micro.get("reversion_risk"),
            "liquidity_state": micro.get("liquidity_state"),
        },
        "market_participation": {
            "participation_state": participation.get("participation_state"),
            "isolated_move_risk": participation.get("isolated_move_risk"),
        },
        "volatility_normalization": {
            "stretch_state": volatility.get("stretch_state"),
            "chase_risk": volatility.get("chase_risk"),
        },
        "downside_asymmetry": {
            "downside_state": downside.get("downside_state"),
            "downside_score": downside_score,
        },
    }


def _ml_authority_safety_blockers(
    *,
    mode: str,
    execution_mode: str,
    min_sample_size: int,
    min_confidence: str,
    max_age_seconds: int,
    prediction_age_seconds: float | None,
) -> list[str]:
    if mode != "live_block":
        return []

    blockers = []
    if execution_mode not in {"cash_safe", "cash_full"}:
        blockers.append(f"execution_mode={execution_mode} is not live-compatible")
    if min_sample_size < 20:
        blockers.append(f"min_sample_size={min_sample_size} below safe floor 20")
    if _ML_CONFIDENCE_RANK.get(min_confidence, -1) < _ML_CONFIDENCE_RANK["medium"]:
        blockers.append(f"min_confidence={min_confidence} below medium")
    if max_age_seconds <= 0:
        blockers.append("max_age_seconds must be > 0 for live_block")
    if prediction_age_seconds is None:
        blockers.append("prediction freshness timestamp missing")
    return blockers


def evaluate_ml_authority_outcome(
    *,
    prediction_gate: dict[str, Any],
    ml_prediction: dict[str, Any] | None,
    ml_authority_config: dict[str, Any] | None,
    execution_mode: str,
) -> MLAuthorityOutcome:
    config = ml_authority_config or {}
    mode = str(config.get("authority_mode") or "observe_only_compare").strip().lower()
    if mode not in {"observe_only_compare", "size_down_only", "paper_block", "live_block"}:
        mode = "observe_only_compare"
    requested_mode = mode

    advisory_decision = prediction_gate.get("ml_prediction_compare_decision")
    negative_decisions = set(config.get("negative_decisions") or ("avoid", "block", "caution"))
    negative_compare = advisory_decision in negative_decisions

    try:
        sample_size = int(
            prediction_gate.get("ml_prediction_sample_size")
            or (ml_prediction or {}).get("sample_size")
            or 0
        )
    except Exception:
        sample_size = 0
    min_sample_size = int(config.get("min_sample_size") or 0)

    confidence = (
        prediction_gate.get("ml_prediction_confidence")
        or (ml_prediction or {}).get("confidence")
        or None
    )
    confidence_key = str(confidence or "").strip().lower()
    min_confidence = str(config.get("min_confidence") or "medium").strip().lower()
    confidence_ok = _ML_CONFIDENCE_RANK.get(confidence_key, -1) >= _ML_CONFIDENCE_RANK.get(
        min_confidence,
        _ML_CONFIDENCE_RANK["medium"],
    )

    max_age_seconds = int(config.get("max_age_seconds") or 0)
    age_seconds = _ml_prediction_age_seconds(ml_prediction or {})
    safety_blockers = _ml_authority_safety_blockers(
        mode=mode,
        execution_mode=execution_mode,
        min_sample_size=min_sample_size,
        min_confidence=min_confidence,
        max_age_seconds=max_age_seconds,
        prediction_age_seconds=age_seconds,
    )
    model_guard = config.get("model_staleness_guard") or {}
    model_fallback_required = False
    if isinstance(model_guard, dict) and model_guard.get("fallback_required"):
        model_fallback_required = True
        safety_blockers.append(
            "model staleness guard requires deterministic fallback: "
            f"{model_guard.get('reason') or model_guard.get('status')}"
        )

    circuit_metadata: dict[str, Any] = {
        "enabled": False,
        "state": "disabled",
        "requested_mode": requested_mode,
        "effective_mode": mode,
    }
    circuit_cfg = circuit_config_from(config)
    if circuit_cfg.get("enabled"):
        failure_reason = _prediction_health_failure_reason(
            ml_prediction=ml_prediction or {},
            age_seconds=age_seconds,
            max_age_seconds=max_age_seconds,
            model_fallback_required=model_fallback_required,
        )
        breaker = MLAuthorityCircuitBreaker(
            path=circuit_cfg["path"],
            threshold=int(circuit_cfg["threshold"]),
            recovery_seconds=int(circuit_cfg["recovery_seconds"]),
        )
        circuit_state = breaker.record(
            failure=bool(failure_reason),
            reason=failure_reason,
        )
        circuit_metadata = {
            "enabled": True,
            "state": circuit_state.state,
            "consecutive_failures": circuit_state.consecutive_failures,
            "threshold": circuit_state.threshold,
            "opened_at": circuit_state.opened_at,
            "open_until": circuit_state.open_until,
            "last_failure_reason": circuit_state.last_failure_reason,
            "requested_mode": requested_mode,
            "effective_mode": mode,
            "open_mode": circuit_cfg["open_mode"],
        }
        if circuit_state.state == "open":
            degraded_mode = str(circuit_cfg["open_mode"] or "observe_only_compare")
            if degraded_mode not in {
                "observe_only_compare",
                "size_down_only",
                "paper_block",
                "live_block",
            }:
                degraded_mode = "observe_only_compare"
            mode = degraded_mode
            circuit_metadata["effective_mode"] = mode
            safety_blockers.append(
                "ML authority circuit open; "
                f"degraded {requested_mode} to {mode}: "
                f"{circuit_state.last_failure_reason or 'recent prediction failures'}"
            )
    safety_check_passed = not safety_blockers
    recency_ok = max_age_seconds <= 0 or (
        age_seconds is not None and age_seconds <= max_age_seconds
    )

    sample_ok = sample_size >= min_sample_size
    qualified = bool(
        negative_compare
        and sample_ok
        and confidence_ok
        and recency_ok
        and not model_fallback_required
    )
    would_block_under_promoted_mode = qualified

    reason_parts = []
    if not negative_compare:
        reason_parts.append(f"ml_compare={advisory_decision or 'none'} is not negative")
    if not sample_ok:
        reason_parts.append(f"sample_size={sample_size} < min_sample_size={min_sample_size}")
    if not confidence_ok:
        reason_parts.append(
            f"confidence={confidence or 'unknown'} < min_confidence={min_confidence}"
        )
    if not recency_ok:
        reason_parts.append(
            f"prediction_age_seconds={age_seconds} > max_age_seconds={max_age_seconds}"
        )
    if safety_blockers:
        reason_parts.append("ML authority refused: " + "; ".join(safety_blockers))
    if not reason_parts:
        reason_parts.append("qualified negative ML compare")

    enforced = False
    effect_on_size = "none"
    effect_on_execution = "none"
    size_cap_pct = None

    if qualified:
        if mode == "size_down_only":
            enforced = True
            effect_on_size = "cap"
            size_cap_pct = float(config.get("size_cap_pct") or 0.80)
        elif mode == "paper_block":
            if execution_mode in {"paper", "dry_run"}:
                enforced = True
                effect_on_execution = "block"
            else:
                reason_parts.append("paper_block not enforced outside paper/dry_run")
        elif mode == "live_block" and safety_check_passed:
            enforced = True
            effect_on_execution = "block"
        elif mode == "live_block":
            reason_parts.append("live_block kill-switch held enforcement disabled")
        elif mode == "observe_only_compare":
            reason_parts.append("negative compare ignored by design in observe_only_compare")

    return MLAuthorityOutcome(
        mode=mode,
        advisory_decision=advisory_decision,
        negative_compare=negative_compare,
        qualified_for_authority=qualified,
        enforced=enforced,
        effect_on_size=effect_on_size,
        effect_on_execution=effect_on_execution,
        reason="; ".join(reason_parts),
        sample_size=sample_size,
        min_sample_size=min_sample_size,
        confidence=confidence,
        min_confidence=min_confidence,
        prediction_age_seconds=age_seconds,
        max_age_seconds=max_age_seconds,
        would_block_under_promoted_mode=would_block_under_promoted_mode,
        safety_check_passed=safety_check_passed,
        safety_blockers=safety_blockers,
        size_cap_pct=size_cap_pct,
        metadata={
            "circuit_breaker": circuit_metadata,
            "requested_mode": requested_mode,
        },
    )
