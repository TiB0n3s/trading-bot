from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable


@dataclass(frozen=True)
class ApprovalDecision:
    approved: bool
    source: str
    confidence: str | None
    reason: str
    category: str | None = None
    claude_payload: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class ClaudeOutcome:
    rejected: bool = False
    approval: ApprovalDecision | None = None
    decision: dict[str, Any] | None = None


@dataclass(frozen=True)
class ApprovalGateOutcome:
    rejected: bool = False
    approval: ApprovalDecision | None = None
    claude_account_state: dict[str, Any] | None = None


@dataclass(frozen=True)
class StageOutcome:
    rejected: bool = False
    approval: ApprovalDecision | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MLAuthorityOutcome:
    mode: str
    advisory_decision: str | None
    negative_compare: bool
    qualified_for_authority: bool
    enforced: bool
    effect_on_size: str
    effect_on_execution: str
    reason: str
    sample_size: int
    min_sample_size: int
    confidence: str | None
    min_confidence: str
    prediction_age_seconds: float | None
    max_age_seconds: int
    would_block_under_promoted_mode: bool
    safety_check_passed: bool
    safety_blockers: list[str] = field(default_factory=list)
    size_cap_pct: float | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "mode": self.mode,
            "authority_mode": self.mode,
            "advisory_decision": self.advisory_decision,
            "negative_compare": self.negative_compare,
            "qualified_for_authority": self.qualified_for_authority,
            "enforced": self.enforced,
            "effect_on_size": self.effect_on_size,
            "effect_on_execution": self.effect_on_execution,
            "reason": self.reason,
            "sample_size": self.sample_size,
            "min_sample_size": self.min_sample_size,
            "confidence": self.confidence,
            "min_confidence": self.min_confidence,
            "prediction_age_seconds": self.prediction_age_seconds,
            "max_age_seconds": self.max_age_seconds,
            "would_block_under_promoted_mode": self.would_block_under_promoted_mode,
            "safety_check_passed": self.safety_check_passed,
            "safety_blockers": list(self.safety_blockers),
            "size_cap_pct": self.size_cap_pct,
        }


@dataclass(frozen=True)
class RejectionAdapter:
    reject_current_signal: Callable[..., bool]
    reject_approval_decision: Callable[..., bool]


def deterministic_rejection(
    *,
    category: str,
    reason: str,
    source: str = "deterministic",
    confidence: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ApprovalDecision:
    return ApprovalDecision(
        approved=False,
        source=source,
        confidence=confidence,
        reason=reason,
        category=category,
        claude_payload=None,
        metadata=metadata or {},
    )


def setup_policy_rejection(reason: str, metadata: dict[str, Any] | None = None) -> ApprovalDecision:
    return deterministic_rejection(
        category="setup_policy",
        reason=reason,
        metadata=metadata,
    )


def trend_confirmation_rejection(
    reason: str, metadata: dict[str, Any] | None = None
) -> ApprovalDecision:
    return deterministic_rejection(
        category="trend_confirmation",
        reason=reason,
        metadata=metadata,
    )


def session_momentum_rejection(
    reason: str, metadata: dict[str, Any] | None = None
) -> ApprovalDecision:
    return deterministic_rejection(
        category="session_momentum_gate",
        reason=reason,
        metadata=metadata,
    )


def prediction_gate_rejection(
    reason: str, metadata: dict[str, Any] | None = None
) -> ApprovalDecision:
    return deterministic_rejection(
        category="prediction_gate",
        reason=reason,
        metadata=metadata,
    )


def live_bias_rejection(
    category: str, reason: str, metadata: dict[str, Any] | None = None
) -> ApprovalDecision:
    return deterministic_rejection(
        category=category,
        reason=reason,
        metadata=metadata,
    )


def strategy_memory_rejection(
    reason: str, metadata: dict[str, Any] | None = None
) -> ApprovalDecision:
    return deterministic_rejection(
        category="strategy_memory",
        reason=reason,
        metadata=metadata,
    )


def opportunity_score_rejection(
    reason: str, metadata: dict[str, Any] | None = None
) -> ApprovalDecision:
    return deterministic_rejection(
        category="opportunity_score",
        reason=reason,
        metadata=metadata,
    )


def decision_policy_rejection(
    reason: str, metadata: dict[str, Any] | None = None
) -> ApprovalDecision:
    return deterministic_rejection(
        category="decision_policy",
        reason=reason,
        metadata=metadata,
    )


def execution_rejection_decision(outcome: Any) -> ApprovalDecision:
    return deterministic_rejection(
        category=getattr(outcome, "rejection_category", None) or "order_path_exception",
        reason=(
            getattr(outcome, "rejection_reason", None)
            or getattr(outcome, "failure_reason", None)
            or "execution rejected"
        ),
        source="execution",
        metadata=getattr(outcome, "metadata", None) or {},
    )
