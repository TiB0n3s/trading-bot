"""Versioned rollout governance for feature-family promotion.

This module turns attribution telemetry into deterministic promotion assessments.
It is intentionally non-authoritative: assessments are report and snapshot
metadata only until a future, explicit authority path consumes them.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


ROLLOUT_CONTRACT_VERSION = "rollout_contract_v1"


class RolloutStatus(str, Enum):
    OBSERVE_ONLY = "observe_only"
    SIZE_DOWN_CANDIDATE = "size_down_candidate"
    NARROW_BLOCK_CANDIDATE = "narrow_block_candidate"
    NOT_READY = "not_ready"


@dataclass(frozen=True)
class RolloutThresholds:
    min_sample_size_size_down: int = 150
    min_sample_size_block: int = 300
    max_missing_rate: float = 0.10
    min_stability_share_size_down: float = 0.60
    min_stability_share_block: float = 0.75
    max_overlap_risk_for_promotion: float = 0.50
    max_overlap_risk_absolute: float = 0.85
    max_false_negative_cost_size_down: float = 0.15
    max_false_negative_cost_block: float = 0.10
    min_false_positive_reduction_size_down: float = 0.03
    min_false_positive_reduction_block: float = 0.05
    min_calibration_quality: str = "medium"
    block_candidate_allowlist: tuple[str, ...] = (
        "portfolio_decision",
    )
    max_status_by_family: dict[str, RolloutStatus] = field(
        default_factory=lambda: {
            "portfolio_decision": RolloutStatus.NARROW_BLOCK_CANDIDATE,
            "execution_quality": RolloutStatus.SIZE_DOWN_CANDIDATE,
            "volatility_normalization": RolloutStatus.SIZE_DOWN_CANDIDATE,
            "market_microstructure": RolloutStatus.SIZE_DOWN_CANDIDATE,
            "downside_asymmetry": RolloutStatus.SIZE_DOWN_CANDIDATE,
            "market_participation": RolloutStatus.OBSERVE_ONLY,
            "market_regime": RolloutStatus.OBSERVE_ONLY,
            "utility_estimate": RolloutStatus.OBSERVE_ONLY,
            "calibrated_confidence": RolloutStatus.OBSERVE_ONLY,
            "setup_structure": RolloutStatus.OBSERVE_ONLY,
        }
    )


@dataclass(frozen=True)
class RolloutAssessment:
    feature_family: str
    report_version: str
    status: RolloutStatus
    family_max_status: RolloutStatus
    sample_size: int
    missing_rate: float | None
    stability_share: float | None
    overlap_risk: float
    false_positive_reduction: float | None
    false_negative_cost: float | None
    calibration_quality: str
    guardrail_failures: list[str] = field(default_factory=list)
    promotion_reasons: list[str] = field(default_factory=list)
    restrictions: dict[str, Any] = field(default_factory=dict)
    review_window_start: str | None = None
    review_window_end: str | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["status"] = self.status.value
        data["family_max_status"] = self.family_max_status.value
        return data


@dataclass(frozen=True)
class RolloutContractPayload:
    report_version: str
    decision_date: str | None
    assessments: list[RolloutAssessment]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "decision_date": self.decision_date,
            "assessments": [assessment.to_dict() for assessment in self.assessments],
        }


_CALIBRATION_RANK = {
    "unknown": 0,
    "unavailable": 0,
    "uncalibrated_prior": 0,
    "thin_sample": 1,
    "low": 1,
    "medium": 2,
    "high": 3,
}

_STATUS_RANK = {
    RolloutStatus.NOT_READY: 0,
    RolloutStatus.OBSERVE_ONLY: 1,
    RolloutStatus.SIZE_DOWN_CANDIDATE: 2,
    RolloutStatus.NARROW_BLOCK_CANDIDATE: 3,
}


def _float(value: Any, default: float | None = None) -> float | None:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _quality_at_least(actual: str, minimum: str) -> bool:
    return _CALIBRATION_RANK.get(actual or "unknown", 0) >= _CALIBRATION_RANK.get(minimum, 2)


def _family_max_status(feature_family: str, thresholds: RolloutThresholds) -> RolloutStatus:
    return thresholds.max_status_by_family.get(feature_family, RolloutStatus.OBSERVE_ONLY)


def _cap_status(status: RolloutStatus, max_status: RolloutStatus) -> RolloutStatus:
    if status == RolloutStatus.NOT_READY:
        return status
    if _STATUS_RANK[status] > _STATUS_RANK[max_status]:
        return max_status
    return status


def _family_overlap(feature_family: str, feature_overlap: list[dict[str, Any]] | None) -> float:
    risk = 0.0
    for item in feature_overlap or []:
        if feature_family in (item.get("left_family"), item.get("right_family")):
            risk = max(risk, float(item.get("overlap_rate") or 0.0))
    return round(risk, 4)


def _best_bucket(family_payload: dict[str, Any]) -> dict[str, Any]:
    best = family_payload.get("best_bucket")
    return best if isinstance(best, dict) else {}


def _max_bucket_value(family_payload: dict[str, Any], key: str) -> float | None:
    values = [
        _float(bucket.get(key))
        for bucket in family_payload.get("buckets", [])
        if isinstance(bucket, dict)
    ]
    values = [value for value in values if value is not None]
    if not values:
        return None
    return round(max(values), 4)


def _restrictions(
    *,
    status: RolloutStatus,
    feature_family: str,
    best_bucket: dict[str, Any],
) -> dict[str, Any]:
    base = {
        "strategy_scope": ["buy_only"],
        "requires_hard_gates_passed": True,
        "cannot_increase_size": True,
        "cannot_submit_orders": True,
        "feature_family": feature_family,
    }
    if status == RolloutStatus.SIZE_DOWN_CANDIDATE:
        return {
            **base,
            "allowed_actions": ["size_down_only"],
            "bucket_scope": [best_bucket.get("bucket") or "best_observed_bucket"],
        }
    if status == RolloutStatus.NARROW_BLOCK_CANDIDATE:
        interactions = best_bucket.get("interactions") or {}
        setup_scope = [
            item.get("bucket")
            for item in interactions.get("setup_label", [])
            if item.get("bucket")
        ][:3]
        regime_scope = [
            item.get("bucket")
            for item in interactions.get("regime", [])
            if item.get("bucket")
        ][:3]
        session_scope = [
            item.get("bucket")
            for item in interactions.get("session_phase", [])
            if item.get("bucket")
        ][:3]
        return {
            **base,
            "allowed_actions": ["narrow_block_candidate_review_only"],
            "bucket_scope": [best_bucket.get("bucket") or "best_observed_bucket"],
            "setup_scope": setup_scope or ["narrow_setup_scope_required"],
            "regime_scope": regime_scope or ["narrow_regime_scope_required"],
            "session_scope": session_scope or ["narrow_session_scope_required"],
            "known_failure_pattern_required": True,
            "global_block_allowed": False,
        }
    return {
        **base,
        "allowed_actions": ["observe_only"],
        "global_block_allowed": False,
    }


def assess_feature_family_rollout(
    *,
    family_payload: dict[str, Any],
    feature_overlap: list[dict[str, Any]] | None = None,
    calibration_quality: str | None = None,
    review_window_start: str | None = None,
    review_window_end: str | None = None,
    thresholds: RolloutThresholds | None = None,
) -> RolloutAssessment:
    thresholds = thresholds or RolloutThresholds()
    feature_family = str(family_payload.get("family") or "unknown")
    sample_size = int(family_payload.get("covered_rows") or 0)
    missing_rate = _float(family_payload.get("missing_rate"))
    stability = family_payload.get("stability") or {}
    stability_share = _float(stability.get("stable_window_share"))
    overlap_risk = _family_overlap(feature_family, feature_overlap)
    best = _best_bucket(family_payload)
    false_positive_reduction = _max_bucket_value(family_payload, "false_positive_reduction")
    false_negative_cost = _max_bucket_value(family_payload, "false_negative_increase")
    if false_negative_cost is not None:
        false_negative_cost = max(0.0, false_negative_cost)
    calibration = calibration_quality or family_payload.get("calibration_quality") or "unknown"

    failures: list[str] = []
    reasons: list[str] = []

    if sample_size < thresholds.min_sample_size_size_down:
        failures.append("sample_size_below_size_down_minimum")
    if missing_rate is None or missing_rate > thresholds.max_missing_rate:
        failures.append("missing_rate_too_high")
    if stability_share is None or stability_share < thresholds.min_stability_share_size_down:
        failures.append("stability_share_too_low")
    if overlap_risk >= thresholds.max_overlap_risk_absolute:
        failures.append("overlap_risk_too_high")

    hard_not_ready = bool(failures)
    status = RolloutStatus.NOT_READY if hard_not_ready else RolloutStatus.OBSERVE_ONLY

    calibration_ok = _quality_at_least(calibration, thresholds.min_calibration_quality)
    overlap_promotable = overlap_risk <= thresholds.max_overlap_risk_for_promotion
    if not calibration_ok and not hard_not_ready:
        failures.append("calibration_quality_below_threshold")
    if not overlap_promotable and not hard_not_ready:
        failures.append("overlap_risk_caps_promotion")

    fp_for_size = (false_positive_reduction or 0.0) >= (
        thresholds.min_false_positive_reduction_size_down
    )
    fn_for_size = (false_negative_cost or 0.0) <= thresholds.max_false_negative_cost_size_down
    if (
        not hard_not_ready
        and calibration_ok
        and overlap_promotable
        and fp_for_size
        and fn_for_size
    ):
        status = RolloutStatus.SIZE_DOWN_CANDIDATE
        reasons.append("false_positive_reduction_supports_size_down")
        reasons.append("false_negative_cost_within_size_down_limit")

    block_allowed = feature_family in thresholds.block_candidate_allowlist
    fp_for_block = (false_positive_reduction or 0.0) >= (
        thresholds.min_false_positive_reduction_block
    )
    fn_for_block = (false_negative_cost or 0.0) <= thresholds.max_false_negative_cost_block
    stable_for_block = (
        stability_share is not None
        and stability_share >= thresholds.min_stability_share_block
    )
    if (
        status == RolloutStatus.SIZE_DOWN_CANDIDATE
        and block_allowed
        and sample_size >= thresholds.min_sample_size_block
        and stable_for_block
        and fp_for_block
        and fn_for_block
    ):
        status = RolloutStatus.NARROW_BLOCK_CANDIDATE
        reasons.append("explicit_block_allowlist")
        reasons.append("block_thresholds_satisfied")
    elif status == RolloutStatus.SIZE_DOWN_CANDIDATE and not block_allowed:
        reasons.append("block_candidacy_not_allowlisted")

    max_status = _family_max_status(feature_family, thresholds)
    capped_status = _cap_status(status, max_status)
    if capped_status != status:
        reasons.append(f"family_initial_target_cap={max_status.value}")
        status = capped_status

    return RolloutAssessment(
        feature_family=feature_family,
        report_version=ROLLOUT_CONTRACT_VERSION,
        status=status,
        family_max_status=max_status,
        sample_size=sample_size,
        missing_rate=missing_rate,
        stability_share=stability_share,
        overlap_risk=overlap_risk,
        false_positive_reduction=false_positive_reduction,
        false_negative_cost=false_negative_cost,
        calibration_quality=str(calibration),
        guardrail_failures=failures,
        promotion_reasons=reasons,
        restrictions=_restrictions(status=status, feature_family=feature_family, best_bucket=best),
        review_window_start=review_window_start,
        review_window_end=review_window_end,
    )


def assess_all_feature_family_rollouts(
    *,
    attribution_payload: Any,
    calibration_summary: dict[str, Any] | None = None,
    decision_date: str | None = None,
    review_window_start: str | None = None,
    review_window_end: str | None = None,
    thresholds: RolloutThresholds | None = None,
) -> RolloutContractPayload:
    if hasattr(attribution_payload, "families"):
        families = list(attribution_payload.families)
        feature_overlap = list(getattr(attribution_payload, "feature_overlap", []) or [])
    else:
        families = list((attribution_payload or {}).get("families") or [])
        feature_overlap = list((attribution_payload or {}).get("feature_overlap") or [])

    calibration_summary = calibration_summary or {}
    assessments = [
        assess_feature_family_rollout(
            family_payload=family,
            feature_overlap=feature_overlap,
            calibration_quality=(
                calibration_summary.get(family.get("family"), {})
                if isinstance(calibration_summary.get(family.get("family")), dict)
                else {}
            ).get("calibration_quality")
            or calibration_summary.get(family.get("family"))
            or family.get("calibration_quality")
            or "unknown",
            review_window_start=review_window_start,
            review_window_end=review_window_end,
            thresholds=thresholds,
        )
        for family in families
    ]
    return RolloutContractPayload(
        report_version=ROLLOUT_CONTRACT_VERSION,
        decision_date=decision_date,
        assessments=assessments,
    )


def telemetry_only_rollout_contract() -> dict[str, Any]:
    return {
        "report_version": ROLLOUT_CONTRACT_VERSION,
        "runtime_effect": "telemetry_only_no_live_authority",
        "assessments": [],
    }
