"""Promotion contract for future ML/brain integration.

This module defines metadata only. Runtime code must not use these values as
approval to change trading behavior.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class BrainIntegrationContract:
    name: str = "ml_brain_integration_v1"
    current_status: str = "research_scaffold"
    runtime_effect: str = "none"
    observe_only_required: bool = True
    allowed_initial_surfaces: tuple[str, ...] = (
        "offline_reports",
        "dataset_exports",
        "shadow_scores",
        "status_read_only",
    )
    prohibited_without_approval: tuple[str, ...] = (
        "order_submission",
        "risk_limit_relaxation",
        "hard_gate_override",
        "broker_behavior_change",
        "position_size_increase",
    )
    promotion_requirements: tuple[str, ...] = (
        "feature_and_label_coverage",
        "walk_forward_validation",
        "prediction_calibration_report",
        "paper_session_shadow_comparison",
        "env_flag_default_off",
        "operator_visible_logging",
        "rollback_plan",
    )
    reusable_bot_logic: dict[str, str] = field(default_factory=lambda: {
        "setup_engine": "Feature snapshot setup labels and scores",
        "daily_symbol_context": "Premarket context and event aggregates",
        "daily_symbol_events": "Catalyst/event counts and future event embeddings",
        "daily_symbol_predictions": "Existing observe-only similarity predictions",
        "strategy.trade_scorer": "Future shadow-only trader-brain score",
        "market_intelligence.tape_reader": "Intraday tape labels from bars",
        "decision_context": "Future normalized intelligence summary features",
        "decision_policy": "Future policy replay labels, not live authority",
    })

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def default_contract() -> dict[str, Any]:
    return BrainIntegrationContract().to_dict()
