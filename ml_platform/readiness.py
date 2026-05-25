"""Retraining readiness contracts for staged ML review."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class RetrainingReadinessReport:
    report_version: str = "retraining_readiness_v1"
    status: str = "contract_only_not_ready"
    runtime_effect: str = "none"
    review_cadence: str = "manual review after 20 trading sessions or drift/performance alert"
    minimum_requirements: dict[str, Any] = field(default_factory=lambda: {
        "labeled_snapshots": 500,
        "feature_coverage_pct": 95.0,
        "label_coverage_pct": 50.0,
        "matched_trade_outcomes": "required before paper influence",
        "rejected_signal_forward_outcomes": "required before rejection-policy claims",
        "walk_forward_splits": 3,
        "purge_and_embargo": "required",
        "calibration_report": "required",
        "rollback_plan": "required",
    })
    current_evidence: dict[str, Any] = field(default_factory=dict)
    promotion_allowed: bool = False
    notes: tuple[str, ...] = (
        "Automatic retraining is disabled by default.",
        "This report is evidence for operator review only.",
        "No runtime model loading or trading behavior changes are allowed from this contract.",
    )

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def retraining_readiness_report(
    *,
    dataset_profile: dict[str, Any],
    dataset_manifest: dict[str, Any],
    trading_sessions_observed: int = 0,
) -> dict[str, Any]:
    """Build a conservative readiness report from existing staged evidence."""
    tables = dataset_profile.get("tables") or {}
    snapshots = int(tables.get("feature_snapshots") or 0)
    labels = int(tables.get("labeled_setups") or 0)
    matched_trades = int(tables.get("matched_trades") or 0)
    label_coverage = float(dataset_profile.get("label_coverage_pct") or 0.0)

    blockers = []
    if snapshots < 500:
        blockers.append("fewer_than_500_feature_snapshots")
    if labels < 500:
        blockers.append("fewer_than_500_labeled_setups")
    if label_coverage < 50.0:
        blockers.append("label_coverage_below_50_pct")
    if matched_trades <= 0:
        blockers.append("missing_matched_trade_outcomes")
    if trading_sessions_observed < 20:
        blockers.append("fewer_than_20_trading_sessions_observed")

    current_evidence = {
        "dataset_id": dataset_manifest.get("dataset_id"),
        "date_range": dataset_manifest.get("date_range"),
        "feature_snapshots": snapshots,
        "labeled_setups": labels,
        "matched_trades": matched_trades,
        "label_coverage_pct": label_coverage,
        "trading_sessions_observed": trading_sessions_observed,
        "blockers": blockers,
    }

    report = RetrainingReadinessReport(current_evidence=current_evidence)
    return report.to_dict()
