"""Approval stage interfaces for the signal pipeline.

This module decides approval state only. It does not submit orders or write DB
rows; callers own persistence and side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from services.signal_models import ApprovalResult, DecisionContext


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
class LegacyClaudeOutcome:
    rejected: bool = False
    approval: ApprovalDecision | None = None
    decision: dict[str, Any] | None = None


@dataclass(frozen=True)
class LegacyApprovalGateOutcome:
    rejected: bool = False
    approval: ApprovalDecision | None = None
    claude_account_state: dict[str, Any] | None = None


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


def trend_confirmation_rejection(reason: str, metadata: dict[str, Any] | None = None) -> ApprovalDecision:
    return deterministic_rejection(
        category="trend_confirmation",
        reason=reason,
        metadata=metadata,
    )


def session_momentum_rejection(reason: str, metadata: dict[str, Any] | None = None) -> ApprovalDecision:
    return deterministic_rejection(
        category="session_momentum_gate",
        reason=reason,
        metadata=metadata,
    )


def prediction_gate_rejection(reason: str, metadata: dict[str, Any] | None = None) -> ApprovalDecision:
    return deterministic_rejection(
        category="prediction_gate",
        reason=reason,
        metadata=metadata,
    )


def live_bias_rejection(category: str, reason: str, metadata: dict[str, Any] | None = None) -> ApprovalDecision:
    return deterministic_rejection(
        category=category,
        reason=reason,
        metadata=metadata,
    )


def strategy_memory_rejection(reason: str, metadata: dict[str, Any] | None = None) -> ApprovalDecision:
    return deterministic_rejection(
        category="strategy_memory",
        reason=reason,
        metadata=metadata,
    )


def opportunity_score_rejection(reason: str, metadata: dict[str, Any] | None = None) -> ApprovalDecision:
    return deterministic_rejection(
        category="opportunity_score",
        reason=reason,
        metadata=metadata,
    )


def decision_policy_rejection(reason: str, metadata: dict[str, Any] | None = None) -> ApprovalDecision:
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


def normalize_claude_decision(
    *,
    action: str,
    decision: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(decision or {})
    reason_text = str(normalized.get("reason", "")).lower()
    defer_phrases = (
        "defer",
        "wait",
        "hold off",
        "lacks sufficient conviction",
        "not enough conviction",
        "until momentum",
        "momentum turns rising",
    )

    if action == "buy" and normalized.get("approved") and any(
        phrase in reason_text for phrase in defer_phrases
    ):
        normalized["approved"] = False
        normalized["confidence"] = "low"
        normalized["position_size_pct"] = 0
        normalized["reason"] = (
            "Rejected by consistency guard: Claude reason indicated deferral/wait "
            "despite approved=true."
        )
        normalized["_consistency_guard_triggered"] = True
    return normalized


def evaluate_approval_decision(
    *,
    signal: dict[str, Any],
    action: str,
    claude_account_state: dict[str, Any],
    evaluate_signal: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    cash_safe_mode: bool,
    market_bias: dict[str, Any] | None,
    account_state: dict[str, Any],
    medium_confidence_override: Callable[..., tuple[bool, str]],
    tape_exception_enabled: bool,
) -> ApprovalDecision:
    raw_decision = evaluate_signal(signal, claude_account_state)
    decision = normalize_claude_decision(action=action, decision=raw_decision)
    confidence = decision.get("confidence")
    reason = str(decision.get("reason", ""))

    if action == "buy" and cash_safe_mode and confidence != "high":
        return ApprovalDecision(
            approved=False,
            source="confidence_gate",
            confidence=confidence,
            reason=f"cash_safe requires confidence=high; got {confidence} (reason: {reason})",
            category="cash_safe_confidence",
            claude_payload=decision,
            metadata={"raw_decision": raw_decision},
        )

    if action == "buy" and confidence == "low":
        return ApprovalDecision(
            approved=False,
            source="confidence_gate",
            confidence=confidence,
            reason=f"Claude returned confidence=low (reason: {reason})",
            category="confidence_gate",
            claude_payload=decision,
            metadata={"raw_decision": raw_decision},
        )

    bias_entry = market_bias or {}
    if action == "buy" and confidence != "high" and bias_entry.get("bias") == "neutral":
        momentum_ctx = account_state.get("momentum") or {}
        tape = account_state.get("tape") or {}
        tape_label = tape.get("label")
        vol_state = momentum_ctx.get("volume_state")
        momentum_state = momentum_ctx.get("momentum_state")
        tape_exception = tape_exception_enabled and (
            momentum_state == "accelerating"
            and vol_state in ("elevated", "surge")
            and tape_label == "clean_momentum"
        )
        if not tape_exception:
            medium_ok, medium_reason = medium_confidence_override(
                decision=decision,
                account_state=account_state,
            )
            if not medium_ok:
                return ApprovalDecision(
                    approved=False,
                    source="confidence_gate",
                    confidence=confidence,
                    reason=(
                        f"neutral_bias requires confidence=high; got {confidence} "
                        f"(reason: {reason})"
                    ),
                    category="confidence_gate",
                    claude_payload=decision,
                    metadata={
                        "gate": "neutral_bias",
                        "momentum_state": momentum_state,
                        "volume_state": vol_state,
                        "tape_label": tape_label,
                        "override_reason": medium_reason,
                    },
                )
            account_state["confidence_gate_medium_override"] = {
                "gate": "neutral_bias",
                "reason": medium_reason,
            }

    if action == "buy" and confidence != "high" and bias_entry.get("entry_quality") == "conditional":
        medium_ok, medium_reason = medium_confidence_override(
            decision=decision,
            account_state=account_state,
        )
        if not medium_ok:
            return ApprovalDecision(
                approved=False,
                source="confidence_gate",
                confidence=confidence,
                reason=(
                    f"conditional_entry_quality requires confidence=high; got {confidence} "
                    f"(reason: {reason})"
                ),
                category="confidence_gate",
                claude_payload=decision,
                metadata={
                    "gate": "conditional_entry_quality",
                    "override_reason": medium_reason,
                },
            )
        account_state["confidence_gate_medium_override"] = {
            "gate": "conditional_entry_quality",
            "reason": medium_reason,
        }

    return ApprovalDecision(
        approved=bool(decision.get("approved")),
        source="claude",
        confidence=confidence,
        reason=reason,
        claude_payload=decision,
        metadata={"raw_decision": raw_decision},
    )


class ApprovalService:
    def evaluate(self, context: DecisionContext) -> ApprovalResult:
        return ApprovalResult(approved=True, reason="deferred_to_live_signal_processor")


def run_legacy_claude_and_confidence(
    *,
    signal: dict[str, Any],
    symbol: str,
    action: str,
    account_state: dict[str, Any],
    claude_account_state: dict[str, Any],
    weekly_symbol_performance: Callable[[str], dict[str, Any]],
    medium_confidence_override: Callable[..., tuple[bool, str]],
    evaluate_signal: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    cash_safe_mode: bool,
    market_bias: dict[str, Any] | None,
    tape_exception_enabled: bool,
    log: Any,
) -> LegacyClaudeOutcome:
    weekly_perf = weekly_symbol_performance(symbol)
    account_state["weekly_symbol_performance"] = weekly_perf
    claude_account_state["weekly_symbol_performance"] = weekly_perf

    approval_decision = evaluate_approval_decision(
        signal=signal,
        action=action,
        claude_account_state=claude_account_state,
        evaluate_signal=evaluate_signal,
        cash_safe_mode=cash_safe_mode,
        market_bias=market_bias or {},
        account_state=account_state,
        medium_confidence_override=medium_confidence_override,
        tape_exception_enabled=tape_exception_enabled,
    )
    decision = dict(approval_decision.claude_payload or {})

    if (approval_decision.metadata or {}).get("raw_decision", {}).get("approved") and decision.get(
        "_consistency_guard_triggered"
    ):
        log.warning(
            f"Decision consistency guard flipped {symbol} BUY to rejected: "
            f"approved=true but reason indicated deferral"
        )

    if approval_decision.category:
        log.warning(
            f"{approval_decision.category} rejected {symbol} {action.upper()}: "
            f"{approval_decision.reason}"
        )
        return LegacyClaudeOutcome(rejected=True, approval=approval_decision)

    return LegacyClaudeOutcome(decision=decision)
