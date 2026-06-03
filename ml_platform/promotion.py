"""Conservative ML promotion gate.

This module can approve candidate/warn metadata, but it cannot make a model
live. Promotion beyond warn-only requires an explicit operator flag and still
only writes registry metadata.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from ml_platform.registry import register_model


PROMOTION_REPORT_VERSION = "ml_promotion_gate_v1"
AUTOMATED_ALLOWED_STATUSES = {"candidate", "observe_only", "warn_only"}


@dataclass(frozen=True)
class PromotionAssessment:
    report_version: str
    runtime_effect: str
    requested_status: str
    allowed: bool
    status_to_register: str | None
    blockers: list[str] = field(default_factory=list)
    evidence: dict[str, Any] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _readiness_blockers(readiness_report: dict[str, Any]) -> list[str]:
    evidence = readiness_report.get("current_evidence") or {}
    blockers = evidence.get("blockers") or []
    return [str(item) for item in blockers if item]


def _validation_evidence(validation_report: dict[str, Any]) -> dict[str, Any]:
    date_scores = validation_report.get("date_scores") or []
    valid = [
        row
        for row in date_scores
        if isinstance(row, dict) and row.get("correlation") is not None
    ]
    avg = validation_report.get("average_correlation")
    latest = valid[0].get("correlation") if valid else None
    positive_sessions = [
        row for row in valid if float(row.get("correlation") or 0.0) > 0.0
    ]
    return {
        "valid_session_count": len(valid),
        "positive_session_count": len(positive_sessions),
        "average_correlation": avg,
        "latest_correlation": latest,
        "warning": bool(validation_report.get("warning")),
        "retraining_recommended": bool(validation_report.get("retraining_recommended")),
    }


def assess_candidate_promotion(
    *,
    readiness_report: dict[str, Any],
    validation_report: dict[str, Any],
    requested_status: str = "candidate",
    explicit_operator_approval: bool = False,
    min_average_correlation: float = 0.0,
    min_valid_sessions: int = 3,
) -> PromotionAssessment:
    requested_status = str(requested_status or "candidate").strip().lower()
    blockers = []
    blockers.extend(f"readiness:{item}" for item in _readiness_blockers(readiness_report))

    evidence = _validation_evidence(validation_report)
    valid_sessions = int(evidence["valid_session_count"])
    avg = evidence.get("average_correlation")
    if valid_sessions < min_valid_sessions:
        blockers.append(f"validation:fewer_than_{min_valid_sessions}_valid_sessions")
    if avg is None:
        blockers.append("validation:missing_average_correlation")
    elif float(avg) <= min_average_correlation:
        blockers.append("validation:average_correlation_not_directional")
    if evidence.get("warning"):
        blockers.append("validation:recent_flat_or_negative_prediction_correlation")

    if requested_status not in AUTOMATED_ALLOWED_STATUSES and not explicit_operator_approval:
        blockers.append("promotion:operator_approval_required_beyond_warn_only")

    allowed = not blockers
    return PromotionAssessment(
        report_version=PROMOTION_REPORT_VERSION,
        runtime_effect="metadata_only_no_live_authority",
        requested_status=requested_status,
        allowed=allowed,
        status_to_register=requested_status if allowed else None,
        blockers=blockers,
        evidence=evidence,
        notes=[
            "Candidate registry writes do not load models into runtime.",
            "Automated promotion is capped at warn_only unless explicit operator approval is supplied.",
        ],
    )


def register_candidate_model(
    *,
    assessment: PromotionAssessment,
    model_id: str,
    artifact_path: str,
    metrics_path: str,
    feature_version: str,
    target: str,
    training_window: str,
    validation_window: str,
    registry_path: Path | str | None = None,
) -> dict[str, Any]:
    if not assessment.allowed or not assessment.status_to_register:
        raise ValueError("promotion assessment is not allowed")
    kwargs: dict[str, Any] = {}
    if registry_path is not None:
        kwargs["registry_path"] = registry_path
    return register_model(
        model_id=model_id,
        artifact_path=artifact_path,
        metrics_path=metrics_path,
        feature_version=feature_version,
        target=target,
        training_window=training_window,
        validation_window=validation_window,
        status=assessment.status_to_register,
        notes="Candidate ML artifact written by automated retraining gate. No live authority.",
        **kwargs,
    )
