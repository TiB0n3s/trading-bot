"""Evaluation layer scaffolding.

Defines the reports the platform should produce before any model influence is
considered. This module records contracts only; it does not run backtests.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvaluationPlan:
    name: str
    required_reports: tuple[str, ...] = (
        "dataset_profile",
        "purged_walk_forward_validation",
        "calibration_report",
        "confusion_matrix",
        "pnl_attribution",
        "decision_delta_report",
        "counterfactual_rejected_signal_report",
        "class_imbalance_report",
        "demotion_readiness_report",
    )
    decision_delta_questions: tuple[str, ...] = (
        "Would this have blocked losing trades?",
        "Would this have skipped winning trades?",
        "Would this have changed sizing only downward?",
        "Did it improve expectancy after costs/slippage assumptions?",
        "Did it beat the null no-ML current bot policy?",
        "Did it beat current Claude plus deterministic gates specifically?",
        "Did it account for rejected-signal counterfactual outcomes?",
    )
    minimum_gates: dict[str, Any] = field(default_factory=lambda: {
        "labeled_snapshots": 500,
        "walk_forward_splits": 3,
        "purge_and_embargo": "required for financial time-series splits",
        "matched_trade_outcomes": "required before paper influence",
        "rejected_signal_forward_outcomes": "required before rejection-policy claims",
        "promotion_default": "observe_only",
    })

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_evaluation_plan() -> dict[str, Any]:
    return EvaluationPlan(name="ml_platform_eval_v1").to_dict()
