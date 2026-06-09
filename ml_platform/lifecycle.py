"""Mandatory ML lifecycle contracts.

This module is deliberately declarative and side-effect free. It prevents new
model surfaces from defining their own weaker promotion path by giving training,
serving, replay, and governance code a single lifecycle vocabulary.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

LIFECYCLE_VERSION = "ml_lifecycle_v1"


@dataclass(frozen=True)
class LifecycleStep:
    key: str
    description: str
    required_for_candidate_registration: bool
    required_for_shadow_serving: bool
    required_for_paper_authority: bool
    evidence_key: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


ML_LIFECYCLE_STEPS: tuple[LifecycleStep, ...] = (
    LifecycleStep(
        key="dataset_build",
        description="Build point-in-time dataset from approved feature and label registries.",
        required_for_candidate_registration=True,
        required_for_shadow_serving=True,
        required_for_paper_authority=True,
        evidence_key="dataset_manifest",
    ),
    LifecycleStep(
        key="manifest",
        description="Write dataset/model manifest with symbol universe, feature version, git SHA, and row counts.",
        required_for_candidate_registration=True,
        required_for_shadow_serving=True,
        required_for_paper_authority=True,
        evidence_key="manifest",
    ),
    LifecycleStep(
        key="feature_parity_validation",
        description="Validate runtime/offline feature parity and point-in-time cutoffs.",
        required_for_candidate_registration=True,
        required_for_shadow_serving=True,
        required_for_paper_authority=True,
        evidence_key="feature_parity",
    ),
    LifecycleStep(
        key="purged_walk_forward_validation",
        description="Evaluate with purged, embargoed walk-forward validation; simple 80/20 is not sufficient.",
        required_for_candidate_registration=True,
        required_for_shadow_serving=True,
        required_for_paper_authority=True,
        evidence_key="purged_walk_forward",
    ),
    LifecycleStep(
        key="calibration_report",
        description="Report Brier score, calibration error, and confidence buckets.",
        required_for_candidate_registration=True,
        required_for_shadow_serving=True,
        required_for_paper_authority=True,
        evidence_key="calibration_report",
    ),
    LifecycleStep(
        key="replay_decision_delta",
        description="Replay actual decisions and quantify approvals, blocks, recoveries, and net friction-adjusted delta.",
        required_for_candidate_registration=True,
        required_for_shadow_serving=True,
        required_for_paper_authority=True,
        evidence_key="replay_decision_delta",
    ),
    LifecycleStep(
        key="cost_slippage_report",
        description="Quantify spread, slippage, execution cost, drawdown effect, and exit behavior.",
        required_for_candidate_registration=True,
        required_for_shadow_serving=True,
        required_for_paper_authority=True,
        evidence_key="cost_slippage_report",
    ),
    LifecycleStep(
        key="promotion_assessment",
        description="Run promotion gate using lifecycle metrics; cannot self-promote to live authority.",
        required_for_candidate_registration=True,
        required_for_shadow_serving=True,
        required_for_paper_authority=True,
        evidence_key="promotion_assessment",
    ),
    LifecycleStep(
        key="registry_write",
        description="Write candidate metadata atomically with explicit status and authority scope.",
        required_for_candidate_registration=True,
        required_for_shadow_serving=True,
        required_for_paper_authority=True,
        evidence_key="registry_write",
    ),
    LifecycleStep(
        key="shadow_serving",
        description="Serve predictions in shadow mode with latency/staleness/fail-open guarantees.",
        required_for_candidate_registration=False,
        required_for_shadow_serving=True,
        required_for_paper_authority=True,
        evidence_key="shadow_serving",
    ),
    LifecycleStep(
        key="monitored_paper_authority",
        description="Allow bounded paper authority only with baseline/counterfactual fields captured.",
        required_for_candidate_registration=False,
        required_for_shadow_serving=False,
        required_for_paper_authority=True,
        evidence_key="monitored_paper_authority",
    ),
    LifecycleStep(
        key="rollback_demotion",
        description="Define rollback/demotion triggers and operator-visible kill switch before authority.",
        required_for_candidate_registration=False,
        required_for_shadow_serving=True,
        required_for_paper_authority=True,
        evidence_key="rollback_demotion",
    ),
)


SIMPLE_SPLIT_VALIDATION_METHODS = {
    "chronological_80_20",
    "chronological_80_20_observe_only",
    "simple_holdout",
    "train_test_split",
}

PROMOTION_ELIGIBLE_VALIDATION_METHODS = {
    "purged_walk_forward",
    "purged_walk_forward_v1",
    "purged_embargoed_walk_forward",
}

REQUIRED_PROMOTION_METRICS = (
    "expected_value_per_decision",
    "false_positive_cost",
    "false_negative_opportunity_cost",
    "avoid_loser_precision",
    "avoid_loser_recall",
    "brier_score",
    "calibration_error",
    "profit_factor",
    "max_drawdown_impact",
    "average_mfe_delta",
    "average_mae_delta",
    "slippage_adjusted_decision_delta",
    "capture_ratio_improvement",
    "regime_specific_performance",
    "symbol_specific_stability",
    "time_of_day_stability",
)

PAPER_LEARNING_CONFOUNDER_FIELDS = (
    "baseline_decision_without_override",
    "override_reason",
    "override_authority_mode",
    "model_policy_version",
    "would_have_blocked_reason",
    "sizing_cap_applied",
    "counterfactual_tracking_status",
    "approval_source_class",
)

APPROVAL_SOURCE_CLASSES = (
    "organic_approval",
    "paper_learning_approval",
    "manual_override",
    "soft_rejection_override",
)


@dataclass(frozen=True)
class LifecycleAssessment:
    report_version: str
    target_stage: str
    ready: bool
    missing_steps: list[str] = field(default_factory=list)
    missing_metrics: list[str] = field(default_factory=list)
    blockers: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def required_steps_for_stage(stage: str) -> tuple[LifecycleStep, ...]:
    stage = str(stage or "").strip().lower()
    if stage in {"candidate", "candidate_registration", "observe_only"}:
        return tuple(row for row in ML_LIFECYCLE_STEPS if row.required_for_candidate_registration)
    if stage in {"shadow", "shadow_serving"}:
        return tuple(row for row in ML_LIFECYCLE_STEPS if row.required_for_shadow_serving)
    if stage in {"paper", "paper_authority", "monitored_paper_authority"}:
        return tuple(row for row in ML_LIFECYCLE_STEPS if row.required_for_paper_authority)
    return ML_LIFECYCLE_STEPS


def validation_method_is_promotion_eligible(method: str | None) -> bool:
    return str(method or "").strip().lower() in PROMOTION_ELIGIBLE_VALIDATION_METHODS


def validation_method_is_simple_split(method: str | None) -> bool:
    return str(method or "").strip().lower() in SIMPLE_SPLIT_VALIDATION_METHODS


def assess_lifecycle_evidence(
    evidence: dict[str, Any],
    *,
    target_stage: str = "candidate_registration",
    metrics: dict[str, Any] | None = None,
    validation_method: str | None = None,
) -> LifecycleAssessment:
    required = required_steps_for_stage(target_stage)
    missing_steps = [
        step.key
        for step in required
        if not bool((evidence.get(step.evidence_key) or {}).get("ready"))
    ]
    metrics = metrics or {}
    missing_metrics = [key for key in REQUIRED_PROMOTION_METRICS if metrics.get(key) is None]
    blockers: list[str] = []
    if validation_method_is_simple_split(validation_method):
        blockers.append("validation:simple_split_not_promotion_eligible")
    if validation_method and not validation_method_is_promotion_eligible(validation_method):
        blockers.append(f"validation:not_purged_walk_forward:{validation_method}")
    blockers.extend(f"lifecycle:missing_step:{key}" for key in missing_steps)
    blockers.extend(f"metrics:missing:{key}" for key in missing_metrics)
    return LifecycleAssessment(
        report_version=LIFECYCLE_VERSION,
        target_stage=target_stage,
        ready=not blockers,
        missing_steps=missing_steps,
        missing_metrics=missing_metrics,
        blockers=blockers,
    )


def lifecycle_contract_summary() -> dict[str, Any]:
    return {
        "report_version": LIFECYCLE_VERSION,
        "steps": [row.to_dict() for row in ML_LIFECYCLE_STEPS],
        "required_promotion_metrics": list(REQUIRED_PROMOTION_METRICS),
        "promotion_eligible_validation_methods": sorted(PROMOTION_ELIGIBLE_VALIDATION_METHODS),
        "simple_split_validation_methods": sorted(SIMPLE_SPLIT_VALIDATION_METHODS),
        "paper_learning_confounder_fields": list(PAPER_LEARNING_CONFOUNDER_FIELDS),
        "approval_source_classes": list(APPROVAL_SOURCE_CLASSES),
    }
