"""Shadow replay scaffolding for future policy/model comparison."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from ml_platform.governance import BASELINE_POLICIES, FRICTION_ASSUMPTIONS


@dataclass(frozen=True)
class ReplayDecisionSummary:
    start_date: str
    end_date: str
    policy: str
    candidate_model: str
    status: str = "scaffold_only_no_runtime_effect"
    same_decision_count: int | None = None
    changed_decision_count: int | None = None
    approved_fewer: int | None = None
    approved_more: int | None = None
    avoided_losers: int | None = None
    missed_winners: int | None = None
    net_simulated_delta: float | None = None
    worst_changed_decision: dict[str, Any] | None = None
    best_changed_decision: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["required_baselines"] = BASELINE_POLICIES
        data["required_friction_assumptions"] = FRICTION_ASSUMPTIONS
        data["note"] = (
            "This command defines the replay output contract only. It does not "
            "load models, change orders, or alter runtime decisions."
        )
        return data


def replay_decisions_scaffold(
    *,
    start_date: str,
    end_date: str,
    policy: str,
    candidate_model: str,
) -> dict[str, Any]:
    return ReplayDecisionSummary(
        start_date=start_date,
        end_date=end_date,
        policy=policy,
        candidate_model=candidate_model,
    ).to_dict()
