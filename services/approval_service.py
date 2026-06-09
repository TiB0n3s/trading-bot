"""Approval stage interfaces for the signal pipeline.

This module decides approval state only. It does not submit orders or write DB
rows; callers own persistence and side effects.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from services import rejection_categories as categories
from services.approval_models import (
    ApprovalDecision,
    ApprovalGateOutcome,
    ClaudeOutcome,
    MLAuthorityOutcome,
    RejectionAdapter,
    StageOutcome,
    decision_policy_rejection,
    deterministic_rejection,
    execution_rejection_decision,
    live_bias_rejection,
    opportunity_score_rejection,
    prediction_gate_rejection,
    session_momentum_rejection,
    setup_policy_rejection,
    strategy_memory_rejection,
    trend_confirmation_rejection,
)
from services.decision import DecisionEngine
from services.historical_bar_meta_label_authority_service import (
    evaluate_historical_bar_meta_label_authority,
)
from services.ml_authority_service import (
    _advisory_feature_size_cap,
    _float_or_none,
    _late_chase_entry_risk,
    evaluate_ml_authority_outcome,
)
from services.signal_models import ApprovalResult, DecisionContext
from src.trading_bot.runtime.authority import AuthorityMatrix

__all__ = [
    "ApprovalDecision",
    "ApprovalGateOutcome",
    "ApprovalService",
    "ClaudeOutcome",
    "MLAuthorityOutcome",
    "RejectionAdapter",
    "StageOutcome",
    "_advisory_feature_size_cap",
    "decision_policy_rejection",
    "deterministic_rejection",
    "evaluate_approval_decision",
    "evaluate_ml_authority_outcome",
    "execution_rejection_decision",
    "live_bias_rejection",
    "opportunity_score_rejection",
    "prediction_gate_rejection",
    "run_claude_and_confidence",
    "run_entry_sanity_gates",
    "run_final_approval_gates",
    "run_intra_session_tape_degradation_gate",
    "run_macro_position_gate",
    "run_prediction_session_tape_gates",
    "run_trend_confirmation_gate",
    "session_momentum_rejection",
    "setup_policy_rejection",
    "strategy_memory_rejection",
    "trend_confirmation_rejection",
]


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

    if (
        action == "buy"
        and normalized.get("approved")
        and any(phrase in reason_text for phrase in defer_phrases)
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


def _store_decision_trace(
    *,
    account_state: dict[str, Any],
    decision: dict[str, Any],
    source: str,
    execution_mode: str,
    exploration: dict[str, Any] | None = None,
) -> None:
    DecisionEngine().store_to_account_state(
        account_state=account_state,
        decision=decision,
        source=source,
        execution_mode=execution_mode,
        exploration=exploration,
    )


def _authority_denied_decision(
    *,
    decision: dict[str, Any],
    source: str,
    execution_mode: str,
) -> dict[str, Any] | None:
    approved = bool(decision.get("approved"))
    if not approved:
        return None
    matrix = AuthorityMatrix()
    if matrix.can(source, "approve", execution_mode):
        return None
    return {
        "approved": False,
        "confidence": decision.get("confidence"),
        "reason": (
            f"AuthorityMatrix denied {source} approve authority in execution_mode={execution_mode}"
        ),
        "position_size_pct": 0,
        "stop_loss_pct": decision.get("stop_loss_pct", 0),
        "take_profit_pct": decision.get("take_profit_pct", 0),
        "authority_denied": matrix.decision(source, "approve", execution_mode),
    }


def _claude_infrastructure_rejection(reason: str) -> tuple[str, str] | None:
    reason_text = str(reason or "").strip()
    reason_lower = reason_text.lower()
    if "parse error" in reason_lower:
        return categories.CLAUDE_PARSE_ERROR, "Claude response parse error"
    if (
        "engine error" in reason_lower
        or "request timed out" in reason_lower
        or "network timeout" in reason_lower
        or "dropped connection" in reason_lower
        or "request cancellation" in reason_lower
    ):
        return categories.CLAUDE_ENGINE_ERROR, "Claude engine error or timeout"
    return None


def _paper_learning_override_decision(
    *,
    action: str,
    decision: dict[str, Any],
    account_state: dict[str, Any],
    execution_mode: str,
    ml_authority_config: dict[str, Any] | None,
) -> dict[str, Any]:
    """Return a paper-only approval override for strong canonical intelligence.

    This runs after all pre-Claude pipeline gates. It cannot revive stale signals,
    broker/account failures, cash-mode signals, or Claude infrastructure failures.
    """
    config = (ml_authority_config or {}).get("paper_learning_authority") or {}
    if (
        action != "buy"
        or execution_mode not in {"paper", "dry_run"}
        or not bool(config.get("enabled"))
    ):
        return {"allowed": False, "reason": "paper learning authority disabled or not applicable"}

    setup_quality = account_state.get("setup_quality") or {}
    buy_opportunity = account_state.get("buy_opportunity") or {}
    prediction_gate = account_state.get("prediction_gate") or {}
    session_gate = account_state.get("session_momentum_gate") or {}

    setup_score = _float_or_none(setup_quality.get("score"))
    buy_score = _float_or_none(buy_opportunity.get("buy_opportunity_score"))
    min_setup = float(config.get("min_setup_score") or 65.0)
    min_buy_score = float(config.get("min_buy_opportunity_score") or 8.0)
    max_size_pct = float(config.get("max_position_size_pct") or 0.75)

    setup_rec = str(setup_quality.get("recommendation") or "").lower()
    setup_action = str(setup_quality.get("policy_action") or "").lower()
    buy_rec = str(buy_opportunity.get("buy_opportunity_recommendation") or "").lower()
    deterministic_gate = str(
        prediction_gate.get("deterministic_signal_quality_decision")
        or prediction_gate.get("prediction_decision")
        or ""
    ).lower()
    session_severity = str(session_gate.get("severity") or "").lower()

    blockers = []
    if setup_action in {"block", "avoid"} or setup_rec == "avoid":
        blockers.append(f"setup_quality={setup_action or setup_rec}")
    if buy_rec in {"avoid", "skip"}:
        blockers.append(f"buy_opportunity={buy_rec}")
    if deterministic_gate == "block":
        blockers.append("deterministic_signal_quality=block")
    if session_severity in {"block", "hard_block"}:
        blockers.append(f"session_gate={session_severity}")
    if setup_score is None or setup_score < min_setup:
        blockers.append(f"setup_score={setup_score} < {min_setup}")
    if buy_score is None or buy_score < min_buy_score:
        blockers.append(f"buy_opportunity_score={buy_score} < {min_buy_score}")

    if blockers:
        return {
            "allowed": False,
            "reason": "; ".join(blockers),
            "setup_score": setup_score,
            "buy_opportunity_score": buy_score,
        }

    requested_size = _float_or_none(decision.get("position_size_pct"))
    if requested_size is None or requested_size <= 0:
        requested_size = max_size_pct
    approved_size = min(requested_size, max_size_pct)

    return {
        "allowed": True,
        "reason": (
            "paper learning authority approved strong canonical intelligence "
            f"after Claude soft rejection: setup_score={setup_score}; "
            f"buy_score={buy_score}; setup={setup_rec or setup_action}; "
            f"buy_rec={buy_rec}"
        ),
        "position_size_pct": approved_size,
        "max_position_size_pct": max_size_pct,
        "setup_score": setup_score,
        "buy_opportunity_score": buy_score,
        "setup_recommendation": setup_rec,
        "buy_opportunity_recommendation": buy_rec,
    }


def _paper_exploration_authority_decision(
    *,
    action: str,
    decision: dict[str, Any],
    account_state: dict[str, Any],
    execution_mode: str,
    ml_authority_config: dict[str, Any] | None,
) -> dict[str, Any]:
    config = (ml_authority_config or {}).get("paper_exploration_authority") or {}
    if action != "buy" or not config.get("enabled") or execution_mode not in {"paper", "dry_run"}:
        return {
            "allowed": False,
            "reason": "paper exploration authority disabled or not applicable",
        }
    authority_matrix = AuthorityMatrix()

    setup_quality = account_state.get("setup_quality") or {}
    buy_opportunity = account_state.get("buy_opportunity") or {}
    prediction_gate = account_state.get("prediction_gate") or {}
    session_gate = account_state.get("session_momentum_gate") or {}
    execution_quality = account_state.get("execution_quality") or {}
    macro_risk = account_state.get("macro_risk") or {}

    setup_score = _float_or_none(setup_quality.get("score"))
    buy_score = _float_or_none(buy_opportunity.get("buy_opportunity_score"))
    prediction_score = _float_or_none(
        prediction_gate.get("prediction_score")
        or prediction_gate.get("ml_prediction_score")
        or account_state.get("prediction_score")
    )

    min_setup = float(config.get("min_setup_score") or 78.0)
    min_buy_score = float(config.get("min_buy_opportunity_score") or 10.0)
    min_prediction = float(config.get("min_prediction_score") or 55.0)
    max_size_pct = float(config.get("max_position_size_pct") or 1.5)
    lift_multiplier = float(config.get("size_lift_multiplier") or 1.25)

    setup_rec = str(setup_quality.get("recommendation") or "").lower()
    setup_action = str(setup_quality.get("policy_action") or "").lower()
    buy_rec = str(buy_opportunity.get("buy_opportunity_recommendation") or "").lower()
    deterministic_gate = str(
        prediction_gate.get("deterministic_signal_quality_decision")
        or prediction_gate.get("prediction_decision")
        or ""
    ).lower()
    session_severity = str(session_gate.get("severity") or "").lower()
    execution_decision = str(execution_quality.get("decision") or "").lower()

    blockers = []
    if macro_risk.get("block_new_buys"):
        blockers.append("macro_risk=block_new_buys")
    if setup_action in {"block", "avoid"} or setup_rec == "avoid":
        blockers.append(f"setup_quality={setup_action or setup_rec}")
    if buy_rec in {"avoid", "skip"}:
        blockers.append(f"buy_opportunity={buy_rec}")
    if deterministic_gate == "block":
        blockers.append("deterministic_signal_quality=block")
    if session_severity in {"block", "hard_block"}:
        blockers.append(f"session_gate={session_severity}")
    if execution_decision == "block":
        blockers.append("execution_quality=block")
    if setup_score is None or setup_score < min_setup:
        blockers.append(f"setup_score={setup_score} < {min_setup}")
    if buy_score is None or buy_score < min_buy_score:
        blockers.append(f"buy_opportunity_score={buy_score} < {min_buy_score}")
    if prediction_score is not None and prediction_score < min_prediction:
        blockers.append(f"prediction_score={prediction_score} < {min_prediction}")
    if setup_rec not in {"buy", "strong_buy", "favor"} and setup_action not in {
        "allow",
        "buy",
    }:
        blockers.append(f"setup_recommendation={setup_rec or setup_action or 'unknown'}")
    if buy_rec not in {"strong_buy_candidate", "buy_candidate", "favor", "allow"}:
        blockers.append(f"buy_opportunity_recommendation={buy_rec or 'unknown'}")

    if blockers:
        return {
            "allowed": False,
            "reason": "; ".join(blockers),
            "setup_score": setup_score,
            "buy_opportunity_score": buy_score,
            "prediction_score": prediction_score,
        }
    approve_authorized = authority_matrix.can("paper_exploration", "approve", execution_mode)
    increase_authorized = authority_matrix.can(
        "paper_exploration",
        "increase_size",
        execution_mode,
    )
    if not approve_authorized and not bool(decision.get("approved")):
        return {"allowed": False, "reason": "authority_matrix_denied_paper_approval"}
    if bool(decision.get("approved")) and not increase_authorized:
        return {"allowed": False, "reason": "authority_matrix_denied_size_increase"}

    requested_size = _float_or_none(decision.get("position_size_pct"))
    if requested_size is None or requested_size <= 0:
        requested_size = _float_or_none(account_state.get("position_size_pct")) or 1.0
    approved = bool(decision.get("approved"))
    final_size = min(
        max_size_pct,
        requested_size * lift_multiplier if approved else max(requested_size, max_size_pct),
    )
    final_size = round(max(0.0, final_size), 4)
    effect = "size_increase" if approved and final_size > requested_size else "paper_approval"
    return {
        "allowed": True,
        "reason": (
            "paper exploration authority used strong deterministic intelligence: "
            f"setup_score={setup_score}; buy_score={buy_score}; "
            f"prediction_score={prediction_score}; setup={setup_rec or setup_action}; "
            f"buy_rec={buy_rec}; effect={effect}"
        ),
        "position_size_pct": final_size,
        "original_position_size_pct": requested_size,
        "max_position_size_pct": max_size_pct,
        "size_lift_multiplier": lift_multiplier,
        "effect": effect,
        "setup_score": setup_score,
        "buy_opportunity_score": buy_score,
        "prediction_score": prediction_score,
        "setup_recommendation": setup_rec,
        "buy_opportunity_recommendation": buy_rec,
        "authority_scope": "paper_only_exploration_after_hard_gates",
        "can_approve_trades": True,
        "can_increase_size": True,
    }


def _historical_bar_meta_label_authority_decision(
    *,
    signal: dict[str, Any],
    action: str,
    decision: dict[str, Any],
    account_state: dict[str, Any],
    execution_mode: str,
    ml_authority_config: dict[str, Any] | None,
) -> dict[str, Any]:
    return evaluate_historical_bar_meta_label_authority(
        symbol=signal.get("symbol") or account_state.get("symbol"),
        action=action,
        decision=decision,
        account_state=account_state,
        execution_mode=execution_mode,
        config=(ml_authority_config or {}).get("historical_bar_meta_label_authority"),
    )


def _approval_from_historical_bar_meta_label(
    *,
    signal: dict[str, Any],
    action: str,
    decision: dict[str, Any],
    account_state: dict[str, Any],
    execution_mode: str,
    ml_authority_config: dict[str, Any] | None,
    raw_decision: dict[str, Any],
    confidence: Any,
) -> ApprovalDecision | None:
    meta_label = _historical_bar_meta_label_authority_decision(
        signal=signal,
        action=action,
        decision=decision,
        account_state=account_state,
        execution_mode=execution_mode,
        ml_authority_config=ml_authority_config,
    )
    if not meta_label.get("allowed"):
        return None

    account_state["historical_bar_meta_label_authority"] = meta_label
    effect = meta_label.get("effect")
    adjusted = dict(decision)
    adjusted["historical_bar_meta_label_authority"] = meta_label

    if effect == "veto":
        adjusted["approved"] = False
        adjusted["confidence"] = "low"
        adjusted["position_size_pct"] = 0
        adjusted["reason"] = meta_label["reason"]
        _store_decision_trace(
            account_state=account_state,
            decision=adjusted,
            source="historical_bar_meta_label_authority",
            execution_mode=execution_mode,
        )
        return ApprovalDecision(
            approved=False,
            source="historical_bar_meta_label_authority",
            confidence="low",
            reason=meta_label["reason"],
            category="historical_bar_meta_label_veto",
            claude_payload=adjusted,
            metadata={
                "raw_decision": raw_decision,
                "historical_bar_meta_label_authority": meta_label,
            },
        )

    if effect in {"paper_approval", "size_increase"}:
        adjusted["approved"] = True
        adjusted["confidence"] = "high" if effect == "size_increase" else "medium"
        adjusted["position_size_pct"] = meta_label["position_size_pct"]
        adjusted["reason"] = meta_label["reason"]
        _store_decision_trace(
            account_state=account_state,
            decision=adjusted,
            source="historical_bar_meta_label_authority",
            execution_mode=execution_mode,
            exploration=meta_label,
        )
        return ApprovalDecision(
            approved=True,
            source="historical_bar_meta_label_authority",
            confidence=adjusted["confidence"],
            reason=meta_label["reason"],
            category=None,
            claude_payload=adjusted,
            metadata={
                "raw_decision": raw_decision,
                "historical_bar_meta_label_authority": meta_label,
            },
        )

    return None


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
    execution_mode: str = "paper",
    ml_authority_config: dict[str, Any] | None = None,
) -> ApprovalDecision:
    raw_decision = evaluate_signal(signal, claude_account_state)
    decision = normalize_claude_decision(action=action, decision=raw_decision)
    confidence = decision.get("confidence")
    reason = str(decision.get("reason", ""))

    if action == "buy":
        infrastructure_rejection = _claude_infrastructure_rejection(reason)
        if infrastructure_rejection:
            category, summary = infrastructure_rejection
            _store_decision_trace(
                account_state=account_state,
                decision=decision,
                source=category,
                execution_mode=execution_mode,
            )
            return ApprovalDecision(
                approved=False,
                source=category,
                confidence=confidence,
                reason=f"{summary}: {reason}",
                category=category,
                claude_payload=decision,
                metadata={
                    "raw_decision": raw_decision,
                    "failure_type": category,
                },
            )

    if action == "buy" and cash_safe_mode and confidence != "high":
        _store_decision_trace(
            account_state=account_state,
            decision=decision,
            source="confidence_gate",
            execution_mode=execution_mode,
        )
        return ApprovalDecision(
            approved=False,
            source="confidence_gate",
            confidence=confidence,
            reason=f"cash_safe requires confidence=high; got {confidence} (reason: {reason})",
            category="cash_safe_confidence",
            claude_payload=decision,
            metadata={"raw_decision": raw_decision},
        )

    if action == "buy":
        meta_label_result = _approval_from_historical_bar_meta_label(
            signal=signal,
            action=action,
            decision=decision,
            account_state=account_state,
            execution_mode=execution_mode,
            ml_authority_config=ml_authority_config,
            raw_decision=raw_decision,
            confidence=confidence,
        )
        if meta_label_result is not None:
            return meta_label_result

    if action == "buy" and confidence == "low":
        exploration = _paper_exploration_authority_decision(
            action=action,
            decision=decision,
            account_state=account_state,
            execution_mode=execution_mode,
            ml_authority_config=ml_authority_config,
        )
        if exploration.get("allowed"):
            adjusted = dict(decision)
            adjusted["approved"] = True
            adjusted["confidence"] = "medium"
            adjusted["position_size_pct"] = exploration["position_size_pct"]
            adjusted["reason"] = exploration["reason"]
            adjusted["paper_exploration_authority"] = exploration
            account_state["paper_exploration_authority"] = exploration
            _store_decision_trace(
                account_state=account_state,
                decision=adjusted,
                source="paper_exploration_authority",
                execution_mode=execution_mode,
                exploration=exploration,
            )
            return ApprovalDecision(
                approved=True,
                source="paper_exploration_authority",
                confidence="medium",
                reason=exploration["reason"],
                category=None,
                claude_payload=adjusted,
                metadata={
                    "raw_decision": raw_decision,
                    "paper_exploration_authority": exploration,
                },
            )
        paper_override = _paper_learning_override_decision(
            action=action,
            decision=decision,
            account_state=account_state,
            execution_mode=execution_mode,
            ml_authority_config=ml_authority_config,
        )
        if paper_override.get("allowed"):
            adjusted = dict(decision)
            adjusted["approved"] = True
            adjusted["confidence"] = "medium"
            adjusted["position_size_pct"] = paper_override["position_size_pct"]
            adjusted["reason"] = paper_override["reason"]
            adjusted["paper_learning_authority_override"] = paper_override
            account_state["paper_learning_authority_override"] = paper_override
            _store_decision_trace(
                account_state=account_state,
                decision=adjusted,
                source="paper_learning_authority",
                execution_mode=execution_mode,
            )
            return ApprovalDecision(
                approved=True,
                source="paper_learning_authority",
                confidence="medium",
                reason=paper_override["reason"],
                category=None,
                claude_payload=adjusted,
                metadata={
                    "raw_decision": raw_decision,
                    "paper_learning_authority_override": paper_override,
                },
            )
        _store_decision_trace(
            account_state=account_state,
            decision=decision,
            source="confidence_gate",
            execution_mode=execution_mode,
        )
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
                exploration = _paper_exploration_authority_decision(
                    action=action,
                    decision=decision,
                    account_state=account_state,
                    execution_mode=execution_mode,
                    ml_authority_config=ml_authority_config,
                )
                if exploration.get("allowed"):
                    adjusted = dict(decision)
                    adjusted["approved"] = True
                    adjusted["confidence"] = "medium"
                    adjusted["position_size_pct"] = exploration["position_size_pct"]
                    adjusted["reason"] = exploration["reason"]
                    adjusted["paper_exploration_authority"] = exploration
                    account_state["paper_exploration_authority"] = exploration
                    _store_decision_trace(
                        account_state=account_state,
                        decision=adjusted,
                        source="paper_exploration_authority",
                        execution_mode=execution_mode,
                        exploration=exploration,
                    )
                    return ApprovalDecision(
                        approved=True,
                        source="paper_exploration_authority",
                        confidence="medium",
                        reason=exploration["reason"],
                        category=None,
                        claude_payload=adjusted,
                        metadata={
                            "raw_decision": raw_decision,
                            "paper_exploration_authority": exploration,
                        },
                    )
                paper_override = _paper_learning_override_decision(
                    action=action,
                    decision=decision,
                    account_state=account_state,
                    execution_mode=execution_mode,
                    ml_authority_config=ml_authority_config,
                )
                if paper_override.get("allowed"):
                    adjusted = dict(decision)
                    adjusted["approved"] = True
                    adjusted["confidence"] = "medium"
                    adjusted["position_size_pct"] = paper_override["position_size_pct"]
                    adjusted["reason"] = paper_override["reason"]
                    adjusted["paper_learning_authority_override"] = paper_override
                    account_state["paper_learning_authority_override"] = paper_override
                    _store_decision_trace(
                        account_state=account_state,
                        decision=adjusted,
                        source="paper_learning_authority",
                        execution_mode=execution_mode,
                    )
                    return ApprovalDecision(
                        approved=True,
                        source="paper_learning_authority",
                        confidence="medium",
                        reason=paper_override["reason"],
                        category=None,
                        claude_payload=adjusted,
                        metadata={
                            "raw_decision": raw_decision,
                            "paper_learning_authority_override": paper_override,
                        },
                    )
                _store_decision_trace(
                    account_state=account_state,
                    decision=decision,
                    source="confidence_gate",
                    execution_mode=execution_mode,
                )
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

    if (
        action == "buy"
        and confidence != "high"
        and bias_entry.get("entry_quality") == "conditional"
    ):
        medium_ok, medium_reason = medium_confidence_override(
            decision=decision,
            account_state=account_state,
        )
        if not medium_ok:
            exploration = _paper_exploration_authority_decision(
                action=action,
                decision=decision,
                account_state=account_state,
                execution_mode=execution_mode,
                ml_authority_config=ml_authority_config,
            )
            if exploration.get("allowed"):
                adjusted = dict(decision)
                adjusted["approved"] = True
                adjusted["confidence"] = "medium"
                adjusted["position_size_pct"] = exploration["position_size_pct"]
                adjusted["reason"] = exploration["reason"]
                adjusted["paper_exploration_authority"] = exploration
                account_state["paper_exploration_authority"] = exploration
                _store_decision_trace(
                    account_state=account_state,
                    decision=adjusted,
                    source="paper_exploration_authority",
                    execution_mode=execution_mode,
                    exploration=exploration,
                )
                return ApprovalDecision(
                    approved=True,
                    source="paper_exploration_authority",
                    confidence="medium",
                    reason=exploration["reason"],
                    category=None,
                    claude_payload=adjusted,
                    metadata={
                        "raw_decision": raw_decision,
                        "paper_exploration_authority": exploration,
                    },
                )
            paper_override = _paper_learning_override_decision(
                action=action,
                decision=decision,
                account_state=account_state,
                execution_mode=execution_mode,
                ml_authority_config=ml_authority_config,
            )
            if paper_override.get("allowed"):
                adjusted = dict(decision)
                adjusted["approved"] = True
                adjusted["confidence"] = "medium"
                adjusted["position_size_pct"] = paper_override["position_size_pct"]
                adjusted["reason"] = paper_override["reason"]
                adjusted["paper_learning_authority_override"] = paper_override
                account_state["paper_learning_authority_override"] = paper_override
                _store_decision_trace(
                    account_state=account_state,
                    decision=adjusted,
                    source="paper_learning_authority",
                    execution_mode=execution_mode,
                )
                return ApprovalDecision(
                    approved=True,
                    source="paper_learning_authority",
                    confidence="medium",
                    reason=paper_override["reason"],
                    category=None,
                    claude_payload=adjusted,
                    metadata={
                        "raw_decision": raw_decision,
                        "paper_learning_authority_override": paper_override,
                    },
                )
            _store_decision_trace(
                account_state=account_state,
                decision=decision,
                source="confidence_gate",
                execution_mode=execution_mode,
            )
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

    if action == "buy" and not bool(decision.get("approved")):
        exploration = _paper_exploration_authority_decision(
            action=action,
            decision=decision,
            account_state=account_state,
            execution_mode=execution_mode,
            ml_authority_config=ml_authority_config,
        )
        if exploration.get("allowed"):
            adjusted = dict(decision)
            adjusted["approved"] = True
            adjusted["confidence"] = "medium"
            adjusted["position_size_pct"] = exploration["position_size_pct"]
            adjusted["reason"] = exploration["reason"]
            adjusted["paper_exploration_authority"] = exploration
            account_state["paper_exploration_authority"] = exploration
            _store_decision_trace(
                account_state=account_state,
                decision=adjusted,
                source="paper_exploration_authority",
                execution_mode=execution_mode,
                exploration=exploration,
            )
            return ApprovalDecision(
                approved=True,
                source="paper_exploration_authority",
                confidence="medium",
                reason=exploration["reason"],
                category=None,
                claude_payload=adjusted,
                metadata={
                    "raw_decision": raw_decision,
                    "paper_exploration_authority": exploration,
                },
            )
        paper_override = _paper_learning_override_decision(
            action=action,
            decision=decision,
            account_state=account_state,
            execution_mode=execution_mode,
            ml_authority_config=ml_authority_config,
        )
        if paper_override.get("allowed"):
            adjusted = dict(decision)
            adjusted["approved"] = True
            adjusted["confidence"] = "medium"
            adjusted["position_size_pct"] = paper_override["position_size_pct"]
            adjusted["reason"] = paper_override["reason"]
            adjusted["paper_learning_authority_override"] = paper_override
            account_state["paper_learning_authority_override"] = paper_override
            _store_decision_trace(
                account_state=account_state,
                decision=adjusted,
                source="paper_learning_authority",
                execution_mode=execution_mode,
            )
            return ApprovalDecision(
                approved=True,
                source="paper_learning_authority",
                confidence="medium",
                reason=paper_override["reason"],
                category=None,
                claude_payload=adjusted,
                metadata={
                    "raw_decision": raw_decision,
                    "paper_learning_authority_override": paper_override,
                },
            )

    if action == "buy" and bool(decision.get("approved")):
        exploration = _paper_exploration_authority_decision(
            action=action,
            decision=decision,
            account_state=account_state,
            execution_mode=execution_mode,
            ml_authority_config=ml_authority_config,
        )
        if exploration.get("allowed") and exploration.get("effect") == "size_increase":
            adjusted = dict(decision)
            adjusted["position_size_pct"] = exploration["position_size_pct"]
            adjusted["paper_exploration_authority"] = exploration
            account_state["paper_exploration_authority"] = exploration
            _store_decision_trace(
                account_state=account_state,
                decision=adjusted,
                source="paper_exploration_authority",
                execution_mode=execution_mode,
                exploration=exploration,
            )
            return ApprovalDecision(
                approved=True,
                source="paper_exploration_authority",
                confidence=confidence,
                reason=exploration["reason"],
                category=None,
                claude_payload=adjusted,
                metadata={
                    "raw_decision": raw_decision,
                    "paper_exploration_authority": exploration,
                },
            )

    authority_denied = (
        _authority_denied_decision(
            decision=decision,
            source="claude",
            execution_mode=execution_mode,
        )
        if action == "buy"
        else None
    )
    if authority_denied:
        _store_decision_trace(
            account_state=account_state,
            decision=authority_denied,
            source="authority_matrix",
            execution_mode=execution_mode,
        )
        return ApprovalDecision(
            approved=False,
            source="authority_matrix",
            confidence=confidence,
            reason=authority_denied["reason"],
            category="authority_matrix",
            claude_payload=authority_denied,
            metadata={
                "raw_decision": raw_decision,
                "authority_denied": authority_denied["authority_denied"],
            },
        )

    _store_decision_trace(
        account_state=account_state,
        decision=decision,
        source="claude",
        execution_mode=execution_mode,
    )
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


def run_claude_and_confidence(
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
    execution_mode: str = "paper",
    ml_authority_config: dict[str, Any] | None = None,
) -> ClaudeOutcome:
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
        execution_mode=execution_mode,
        ml_authority_config=ml_authority_config,
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
        return ClaudeOutcome(rejected=True, approval=approval_decision)

    return ClaudeOutcome(decision=decision)


def run_macro_position_gate(
    *,
    symbol: str,
    action: str,
    price: Any,
    account_state: dict[str, Any],
    context_runtime: Any,
    current_et: Any,
    macro_risk: dict[str, Any],
    macro_position_count_floor: float,
    get_latest_session_momentum: Callable[[str], dict[str, Any] | None],
    session_momentum_is_fresh: Callable[[dict[str, Any]], bool],
    weakest_position_context: Callable[[dict[str, Any]], dict[str, Any] | None],
    evaluate_buy_opportunity: Callable[..., dict[str, Any]],
    required_buy_confirmations: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    try_portfolio_rotation: Callable[..., tuple[bool, str, dict[str, Any]]],
    get_account_state: Callable[[], dict[str, Any]],
    sleep: Callable[[float], None],
    log: Any,
) -> StageOutcome:
    if action != "buy":
        return StageOutcome()

    if macro_risk.get("block_new_buys"):
        return StageOutcome(
            rejected=True,
            approval=deterministic_rejection(
                category="macro_risk",
                reason=macro_risk.get("reason", "macro regime blocks new buys"),
                metadata=macro_risk,
            ),
        )

    max_new_positions = macro_risk.get("max_new_positions", 8)
    open_count = account_state.get("open_position_count", 0)
    open_positions = account_state.get("open_positions") or []
    if open_positions:
        effective_count = sum(
            1
            for position in open_positions
            if float(position.get("market_value") or 0) >= macro_position_count_floor
        )
    else:
        effective_count = open_count

    if effective_count < max_new_positions:
        return StageOutcome()

    candidate_session = None
    try:
        candidate_session = get_latest_session_momentum(symbol)
        if candidate_session and not session_momentum_is_fresh(candidate_session):
            candidate_session = None
    except Exception as exc:
        log.warning(f"macro_position_limit session lookup failed for {symbol}: {exc}")
        candidate_session = None

    if candidate_session:
        account_state["session_momentum"] = candidate_session

    def session_value(key: str, fallback_key: str | None = None):
        if candidate_session and candidate_session.get(key) is not None:
            return candidate_session.get(key)
        if fallback_key:
            return account_state.get(fallback_key)
        return None

    candidate_session_score = session_value("trend_score", "session_trend_score")
    candidate_session_label = session_value("trend_label", "session_trend_label")
    candidate_return = session_value("session_return_pct", "session_return_pct")
    candidate_vwap = session_value(
        "distance_from_vwap_pct",
        "session_distance_from_vwap_pct",
    )

    weakest = weakest_position_context(account_state)

    if weakest:
        replacement_hint = "observe_only"
        reason = (
            f"open_position_count={open_count} effective={effective_count} >= macro max_new_positions={max_new_positions}; "
            f"candidate={symbol} session={candidate_session_label}/{candidate_session_score} "
            f"return={candidate_return}% vwap_dist={candidate_vwap}%; "
            f"weakest_holding={weakest.get('symbol')} "
            f"plpc={weakest.get('unrealized_plpc'):.2f}% "
            f"replacement_hint={replacement_hint}"
        )
    else:
        reason = (
            f"open_position_count={open_count} effective={effective_count} >= macro max_new_positions={max_new_positions}; "
            f"candidate={symbol} session={candidate_session_label}/{candidate_session_score} "
            f"return={candidate_return}% vwap_dist={candidate_vwap}%; "
            f"weakest_holding=unknown"
        )

    try:
        macro_limit_opportunity_obs = context_runtime.build_buy_opportunity_observation(
            trend=context_runtime.deps.trend_table.get(symbol) or {},
            bias_entry=context_runtime.deps.market_bias.get(symbol) or {},
            evaluate_buy_opportunity=evaluate_buy_opportunity,
            required_buy_confirmations=required_buy_confirmations,
            log_prefix="BUY opportunity macro-limit",
        )
        macro_limit_buy_opportunity = macro_limit_opportunity_obs.data
        macro_buy_score = macro_limit_buy_opportunity.get("buy_opportunity_score")
        macro_buy_rec = macro_limit_buy_opportunity.get("buy_opportunity_recommendation")
        reason = f"{reason}; buy_score={macro_buy_score}; buy_rec={macro_buy_rec}"
    except Exception as exc:
        log.warning(f"BUY opportunity macro-limit scoring failed for {symbol}: {exc}")

    rotated, rotation_reason, rotation_info = try_portfolio_rotation(
        symbol,
        price,
        account_state,
        current_et,
    )

    if rotated:
        account_state["portfolio_rotation"] = rotation_info
        log.warning(
            f"Portfolio rotation submitted for {symbol}: {rotation_reason}; "
            "waiting briefly for Alpaca position state to refresh"
        )

        sleep(2)
        refreshed_state = get_account_state() or {}
        refreshed_open_count = refreshed_state.get("open_position_count", open_count)

        if refreshed_open_count < max_new_positions:
            account_state.update(refreshed_state)
            log.warning(
                f"Portfolio rotation freed a slot for {symbol}: "
                f"open_position_count {open_count} -> {refreshed_open_count}; "
                "continuing BUY pipeline"
            )
            return StageOutcome()

        pending_reason = (
            f"rotation_pending: {rotation_reason}; "
            f"open_position_count still {refreshed_open_count} >= "
            f"macro max_new_positions={max_new_positions}; original_reason={reason}"
        )
        log.warning(f"Portfolio rotation pending for {symbol}: {pending_reason}")
        return StageOutcome(
            rejected=True,
            approval=deterministic_rejection(
                category="portfolio_rotation_pending",
                reason=pending_reason,
                metadata={"rotation_info": rotation_info},
            ),
        )

    reason = f"{reason}; rotation_not_taken={rotation_reason}"
    return StageOutcome(
        rejected=True,
        approval=deterministic_rejection(
            category="macro_position_limit",
            reason=reason,
            metadata={
                "open_position_count": open_count,
                "effective_count": effective_count,
                "max_new_positions": max_new_positions,
                "rotation_reason": rotation_reason,
            },
        ),
    )


def run_trend_confirmation_gate(
    *,
    symbol: str,
    action: str,
    current_et: Any,
    context_runtime: Any,
    required_buy_confirmations: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    required_sell_confirmations: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    is_fast_lane_buy_flip: Callable[..., bool],
    is_fast_lane_sell_flip: Callable[..., bool],
    market_open_minutes: int,
    open_momentum_fast_lane_enabled: bool,
    iex_thin_symbols: set[str],
    adaptive_buy_confirmation_enabled: bool,
    log: Any,
) -> StageOutcome:
    if action not in ("buy", "sell"):
        return StageOutcome()

    trend_obs = context_runtime.build_trend_confirmation_observation(
        current_et=current_et,
        required_buy_confirmations=required_buy_confirmations,
        required_sell_confirmations=required_sell_confirmations,
        is_fast_lane_buy_flip=is_fast_lane_buy_flip,
        is_fast_lane_sell_flip=is_fast_lane_sell_flip,
        market_open_minutes=market_open_minutes,
        open_momentum_fast_lane_enabled=open_momentum_fast_lane_enabled,
        iex_thin_symbols=iex_thin_symbols,
    )
    trend = trend_obs.data
    trend_confirmation = trend_obs.confirmation
    direction = trend_obs.direction
    strength = trend_obs.strength
    consecutive_count = trend_obs.consecutive_count
    last_signal = trend_obs.last_signal

    if action == "buy":
        adaptive_confirmation = trend_confirmation.get("adaptive_confirmation") or {}
        required = int(trend_confirmation.get("required_confirmations") or 3)

        if direction != "bullish" or last_signal != "buy":
            reason = f"direction={direction} last_signal={last_signal} required={required}"
            log.info(f"Trend confirmation BUY observe-only for {symbol}: {reason}")

        fast_lane_buy_flip = bool(trend_confirmation.get("fast_lane_buy_flip"))
        open_momentum_fast_lane = bool(trend_confirmation.get("open_momentum_fast_lane"))

        log.info(
            f"Trend confirmation BUY for {symbol}: "
            f"required={required} "
            f"count={consecutive_count} "
            f"direction={direction} "
            f"strength={strength} "
            f"last_signal={last_signal} "
            f"flip_event={trend.get('flip_event')} "
            f"fast_lane_buy_flip={fast_lane_buy_flip} "
            f"open_momentum_fast_lane={open_momentum_fast_lane} "
            f"(elapsed={trend_confirmation.get('session_elapsed_minutes')}min "
            f"momentum={trend_confirmation.get('momentum_state')} "
            f"vol={trend_confirmation.get('volume_state')} "
            f"vol_ok={trend_confirmation.get('volume_ok')} "
            f"iex_thin={trend_confirmation.get('iex_thin')} "
            f"bias={trend_confirmation.get('bias')}) "
            f"adaptive_reason={adaptive_confirmation.get('reason')}"
        )
        if open_momentum_fast_lane and consecutive_count < required:
            log.info(
                f"Open-momentum fast lane granted for {symbol}: "
                f"elapsed={trend_confirmation.get('session_elapsed_minutes')}min "
                f"count={consecutive_count} "
                f"momentum={trend_confirmation.get('momentum_state')} "
                f"vol={trend_confirmation.get('volume_state')} "
                f"iex_thin={trend_confirmation.get('iex_thin')}"
            )

        if not (fast_lane_buy_flip or open_momentum_fast_lane) and consecutive_count < required:
            reason = (
                f"consecutive_buy_count={consecutive_count} "
                f"< required={required} "
                f"strength={strength} "
                f"flip_event={trend.get('flip_event')} "
                f"adaptive_reason={adaptive_confirmation.get('reason')}"
            )

            if adaptive_buy_confirmation_enabled:
                return StageOutcome(
                    rejected=True,
                    approval=trend_confirmation_rejection(
                        reason,
                        metadata=trend_confirmation,
                    ),
                )
            log.info(f"Trend confirmation BUY observe-only for {symbol}: {reason}")

        return StageOutcome()

    sell_confirmation = trend_confirmation.get("sell_confirmation") or {}
    required = int(trend_confirmation.get("required_confirmations") or 2)

    if direction != "bearish" or last_signal != "sell":
        reason = f"direction={direction} last_signal={last_signal} required={required}"
        return StageOutcome(
            rejected=True,
            approval=trend_confirmation_rejection(
                reason,
                metadata=trend_confirmation,
            ),
        )

    fast_lane_sell_flip = bool(trend_confirmation.get("fast_lane_sell_flip"))

    log.info(
        f"Trend confirmation SELL for {symbol}: "
        f"required={required} "
        f"count={consecutive_count} "
        f"direction={direction} "
        f"strength={strength} "
        f"last_signal={last_signal} "
        f"flip_event={trend.get('flip_event')} "
        f"fast_lane_sell_flip={fast_lane_sell_flip} "
        f"sell_reason={sell_confirmation.get('reason')}"
    )

    if not fast_lane_sell_flip and consecutive_count < required:
        reason = (
            f"consecutive_sell_count={consecutive_count} "
            f"< required={required} "
            f"strength={strength} "
            f"flip_event={trend.get('flip_event')}"
        )
        return StageOutcome(
            rejected=True,
            approval=trend_confirmation_rejection(
                reason,
                metadata=trend_confirmation,
            ),
        )

    return StageOutcome()


def run_entry_sanity_gates(
    *,
    symbol: str,
    action: str,
    account_state: dict[str, Any],
    bias_entry: dict[str, Any],
    existing_position: Any,
    apply_market_bias_context: Callable[..., Any],
) -> StageOutcome:
    if action != "buy":
        return StageOutcome()

    if bias_entry:
        fundamental_score = bias_entry.get("fundamental_score")
        if fundamental_score in ("bearish", "strong_bearish"):
            return StageOutcome(
                rejected=True,
                approval=deterministic_rejection(
                    category="fundamental_score",
                    reason=f"fundamental_score={fundamental_score}",
                    metadata={"bias_entry": bias_entry},
                ),
            )

    apply_market_bias_context(
        action=action,
        account_state=account_state,
        bias_entry=bias_entry,
    )

    if bias_entry:
        entry_quality = bias_entry.get("entry_quality")
        if entry_quality in ("do_not_chase", "avoid_chasing"):
            reason = (
                f"entry_quality={entry_quality} risk_level={bias_entry.get('risk_level') or '-'}"
            )
            return StageOutcome(
                rejected=True,
                approval=deterministic_rejection(
                    category="chase_prevention",
                    reason=reason,
                    metadata={"bias_entry": bias_entry},
                ),
            )

    if existing_position:
        risk_level = account_state.get("risk_level")
        momentum = account_state.get("momentum") or {}
        momentum_direction = momentum.get("direction")

        if risk_level in ("high", "very_high") and momentum_direction != "rising":
            reason = (
                f"existing position with risk_level={risk_level} "
                f"and momentum_direction={momentum_direction or 'unknown'}"
            )
            return StageOutcome(
                rejected=True,
                approval=deterministic_rejection(
                    category="addon_momentum_gate",
                    reason=reason,
                    metadata={
                        "risk_level": risk_level,
                        "momentum": momentum,
                        "symbol": symbol,
                    },
                ),
            )

    return StageOutcome()


def run_prediction_session_tape_gates(
    *,
    symbol: str,
    action: str,
    execution_mode: str,
    account_state: dict[str, Any],
    context_runtime: Any,
    evaluate_signal_quality_gate: Callable[..., dict[str, Any]],
    get_cached_prediction: Callable[[str], dict[str, Any] | None],
    ml_prediction_bucket: Callable[[Any], str],
    evaluate_buy_opportunity: Callable[..., dict[str, Any]],
    required_buy_confirmations: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    live_bias_override: Callable[..., dict[str, Any]],
    evaluate_session_momentum_gate: Callable[..., dict[str, Any]],
    apply_size_cap: Callable[..., Any],
    env_float: Callable[[str, float], float],
    prediction_soft_avoid_min_sample_size: int,
    enforce_prediction_blocks: bool,
    enforce_prediction_watch_in_cash: bool,
    prediction_gate_mode: str,
    ml_authority_config: dict[str, Any] | None,
    is_cash_mode: Callable[[], bool],
    enforce_session_momentum_gate: bool,
    is_degraded_setup: Callable[[dict[str, Any]], bool],
    log: Any,
) -> StageOutcome:
    if action != "buy":
        return StageOutcome()

    trend = context_runtime.deps.trend_table.get(symbol) or {}
    bias_entry = context_runtime.deps.market_bias.get(symbol) or {}
    setup_obs = account_state.get("setup_observation") or {}
    prediction_obs = context_runtime.build_prediction_observation(
        trend=trend,
        bias_entry=bias_entry,
        evaluate_signal_quality_gate=evaluate_signal_quality_gate,
        get_cached_prediction=get_cached_prediction,
        ml_prediction_bucket=ml_prediction_bucket,
    )
    prediction_gate = prediction_obs.data
    ml_prediction = account_state.get("ml_prediction") or {}

    ml_score_raw = prediction_gate.get("ml_prediction_score")
    ml_sample = int(prediction_gate.get("ml_prediction_sample_size") or 0)
    setup_action = setup_obs.get("setup_policy_action")
    setup_label = setup_obs.get("setup_label")

    is_weak_ml_bucket = (
        ml_score_raw is not None
        and float(ml_score_raw) < 45
        and ml_sample >= prediction_soft_avoid_min_sample_size
    )
    is_degraded_setup_now = is_degraded_setup(setup_obs)

    if is_weak_ml_bucket and is_degraded_setup_now:
        reason = (
            f"ml_prediction_score={float(ml_score_raw):.1f} (weak_below_45); "
            f"ml_sample_size={ml_sample}; "
            f"setup_policy_action={setup_action}; "
            f"setup_label={setup_label!r}"
        )
        apply_size_cap(
            account_state,
            cap_pct=0.5,
            state_key="weak_prediction_setup_gate",
            payload={
                "triggered": True,
                "ml_score": ml_score_raw,
                "ml_sample_size": ml_sample,
                "setup_action": setup_action,
                "setup_label": setup_label,
                "size_cap_pct": 0.5,
                "reason": reason,
            },
        )
        log.warning(
            f"Weak-prediction + degraded-setup gate for {symbol}: size capped at 0.5%; {reason}"
        )
    else:
        account_state["weak_prediction_setup_gate"] = {
            "triggered": False,
            "ml_score": ml_score_raw,
            "ml_sample_size": ml_sample,
            "is_weak_ml": is_weak_ml_bucket,
            "is_degraded_setup": is_degraded_setup_now,
        }

    ml_confidence = prediction_gate.get("ml_prediction_confidence") or ""
    is_confident_weak_prediction = (
        is_weak_ml_bucket
        and ml_confidence in ("medium", "high")
        and not is_degraded_setup_now
        and setup_action not in ("boost",)
    )
    if is_confident_weak_prediction:
        pred_only_cap = env_float("PREDICTION_CONFIDENT_WEAK_SIZE_CAP_PCT", 0.80)
        apply_size_cap(
            account_state,
            cap_pct=pred_only_cap,
            state_key="prediction_confident_weak_cap",
            payload={
                "ml_score": ml_score_raw,
                "ml_confidence": ml_confidence,
                "cap_pct": pred_only_cap,
            },
        )
        log.info(
            f"Prediction confident-weak size cap for {symbol}: "
            f"score={ml_score_raw} confidence={ml_confidence} → {pred_only_cap}%"
        )

    ml_authority = evaluate_ml_authority_outcome(
        prediction_gate=prediction_gate,
        ml_prediction=ml_prediction,
        ml_authority_config=ml_authority_config,
        execution_mode=execution_mode,
    )
    ml_authority_payload = ml_authority.to_dict()
    prediction_gate["ml_authority"] = ml_authority_payload
    account_state["ml_outcome"] = {
        "advisory_decision": ml_authority.advisory_decision,
        "authority_mode": ml_authority.mode,
        "qualified_for_authority": ml_authority.qualified_for_authority,
        "enforced": ml_authority.enforced,
        "effect_on_size": ml_authority.effect_on_size,
        "effect_on_execution": ml_authority.effect_on_execution,
        "would_block_under_promoted_mode": ml_authority.would_block_under_promoted_mode,
        "safety_check_passed": ml_authority.safety_check_passed,
        "safety_blockers": list(ml_authority.safety_blockers),
        "size_cap_pct": ml_authority.size_cap_pct,
        "sample_size": ml_authority.sample_size,
        "confidence": ml_authority.confidence,
        "prediction_age_seconds": ml_authority.prediction_age_seconds,
        "max_age_seconds": ml_authority.max_age_seconds,
        "reason": ml_authority.reason,
    }
    account_state["ml_authority"] = ml_authority_payload
    account_state["ml_authority_mode"] = ml_authority.mode
    account_state["ml_authority_triggered"] = ml_authority.enforced
    account_state["ml_authority_reason"] = ml_authority.reason

    if ml_authority.enforced and ml_authority.effect_on_size == "cap":
        apply_size_cap(
            account_state,
            cap_pct=float(ml_authority.size_cap_pct or 0.80),
            state_key="ml_authority_size_cap",
            payload=ml_authority_payload,
        )
        log.warning(
            f"ML authority size-down for {symbol}: mode={ml_authority.mode} "
            f"compare={ml_authority.advisory_decision} cap={ml_authority.size_cap_pct} "
            f"reason={ml_authority.reason}"
        )

    if ml_authority.enforced and ml_authority.effect_on_execution == "block":
        reason = (
            f"ml_authority_mode={ml_authority.mode}; "
            f"compare={ml_authority.advisory_decision}; "
            f"sample_size={ml_authority.sample_size}; "
            f"confidence={ml_authority.confidence}; "
            f"reason={ml_authority.reason}"
        )
        return StageOutcome(
            rejected=True,
            approval=prediction_gate_rejection(
                reason,
                metadata={
                    "prediction_gate": prediction_gate,
                    "ml_authority": ml_authority_payload,
                },
            ),
        )

    context_runtime.build_buy_opportunity_observation(
        trend=trend,
        bias_entry=bias_entry,
        evaluate_buy_opportunity=evaluate_buy_opportunity,
        required_buy_confirmations=required_buy_confirmations,
        prediction_gate=prediction_gate,
        log_prefix="BUY opportunity",
    )

    prediction_decision = prediction_gate.get("prediction_decision")

    bias_override = live_bias_override(
        symbol=symbol,
        bias_entry=bias_entry,
        trend=trend,
        setup_obs=setup_obs,
        prediction_gate=prediction_gate,
        momentum=account_state.get("momentum") or {},
    )

    account_state["market_bias_effective"] = bias_override.get("effective_bias")
    account_state["market_bias_override_reason"] = bias_override.get("reason")

    effective_bias = bias_override.get("effective_bias")
    allow_buy_from_bias = bool(bias_override.get("allow_buy"))

    if effective_bias == "avoid_hard":
        reason = (
            f"effective_bias={effective_bias} "
            f"confidence={bias_entry.get('confidence', '')} "
            f"reason={bias_override.get('reason')}; "
            f"context_reason={bias_entry.get('reason', '')}"
        )
        return StageOutcome(
            rejected=True,
            approval=live_bias_rejection(
                "market_bias_avoid",
                reason,
                metadata=bias_override,
            ),
        )

    if effective_bias == "avoid_soft" and not allow_buy_from_bias:
        prediction_sample_size = int(
            prediction_gate.get("ml_prediction_sample_size")
            or ml_prediction.get("sample_size")
            or 0
        )
        reason = (
            f"effective_bias={effective_bias}; "
            f"{bias_override.get('reason')}; "
            f"prediction_sample_size={prediction_sample_size}; "
            f"min_sample_size={prediction_soft_avoid_min_sample_size}; "
            f"context_reason={bias_entry.get('reason', '')}"
        )
        if prediction_sample_size >= prediction_soft_avoid_min_sample_size:
            return StageOutcome(
                rejected=True,
                approval=live_bias_rejection(
                    "soft_avoid_prediction_gate",
                    reason,
                    metadata=bias_override,
                ),
            )

        log.warning(f"Soft-avoid prediction gate not enforced for {symbol}: {reason}")
        account_state["soft_avoid_prediction_gate_bypassed"] = True
        account_state["soft_avoid_prediction_gate_bypass_reason"] = reason

    if effective_bias == "live_override_neutral" and not allow_buy_from_bias:
        reason = (
            f"effective_bias={effective_bias}; "
            f"{bias_override.get('reason')}; "
            f"context_reason={bias_entry.get('reason', '')}"
        )
        return StageOutcome(
            rejected=True,
            approval=live_bias_rejection(
                "live_bias_downgrade",
                reason,
                metadata=bias_override,
            ),
        )

    if effective_bias == "live_override_buy":
        log.info(
            f"Live evidence overrode pre-market bias for {symbol} BUY: "
            f"{bias_override.get('reason')}"
        )

    should_block_prediction = (enforce_prediction_blocks and prediction_decision == "block") or (
        enforce_prediction_watch_in_cash and is_cash_mode() and prediction_decision == "watch"
    )

    prediction_would_block = prediction_decision == "block" or (
        is_cash_mode() and prediction_decision == "watch"
    )

    if prediction_gate_mode == "warn" and prediction_would_block:
        log.warning(
            f"Prediction gate warn-only for {symbol} BUY: "
            f"mode={execution_mode} prediction_gate_mode={prediction_gate_mode} "
            f"score={prediction_gate.get('prediction_score')} "
            f"decision={prediction_decision} "
            f"reason={prediction_gate.get('prediction_reason')}"
        )

    if should_block_prediction:
        reason = (
            f"mode={execution_mode} prediction_gate_mode={prediction_gate_mode} "
            f"score={prediction_gate.get('prediction_score')} "
            f"decision={prediction_decision} "
            f"reason={prediction_gate.get('prediction_reason')}"
        )
        return StageOutcome(
            rejected=True,
            approval=prediction_gate_rejection(reason, metadata=prediction_gate),
        )

    session_gate = evaluate_session_momentum_gate(
        session_momentum=account_state.get("session_momentum") or {},
        prediction_gate=prediction_gate,
        setup_obs=setup_obs,
        trend=trend,
    )
    account_state["session_momentum_gate"] = session_gate
    account_state["session_gate_outcome"] = {
        "advisory_decision": "block"
        if session_gate.get("would_block")
        else session_gate.get("severity"),
        "authority_mode": "enforced" if enforce_session_momentum_gate else "observe_only",
        "enforced": bool(enforce_session_momentum_gate and session_gate.get("would_block")),
        "effect_on_size": "cap"
        if session_gate.get("severity")
        in ("soft_negative", "reversal_caution", "hard_negative", "mature_chase_caution")
        else "none",
        "effect_on_execution": "block"
        if enforce_session_momentum_gate and session_gate.get("would_block")
        else "none",
        "reason": session_gate.get("reason"),
    }

    if session_gate.get("would_block"):
        reason = session_gate.get("reason", "session momentum gate")
        if enforce_session_momentum_gate:
            return StageOutcome(
                rejected=True,
                approval=session_momentum_rejection(reason, metadata=session_gate),
            )
        log.info(
            f"Session momentum gate observe-only for {symbol} BUY: "
            f"{session_gate.get('severity')} {reason}"
        )
    elif session_gate.get("severity") == "reversal_caution":
        log.info(
            f"Session reversal_attempt for {symbol} BUY — caution sizing flagged: "
            f"{session_gate.get('reason')}"
        )
        account_state["session_gate_size_hint"] = "reduce"
    elif session_gate.get("severity") == "mature_chase_caution":
        log.info(
            f"Mature long-horizon chase caution for {symbol} BUY — reduced sizing flagged: "
            f"{session_gate.get('reason')}"
        )
        account_state["session_gate_size_hint"] = "reduce"

    severity = session_gate.get("severity")
    session_cap = None
    if severity == "soft_negative":
        session_cap = env_float("SESSION_SOFT_NEGATIVE_SIZE_CAP_PCT", 0.80)
    elif severity == "reversal_caution":
        session_cap = env_float("SESSION_REVERSAL_CAUTION_SIZE_CAP_PCT", 0.90)
    elif severity == "mature_chase_caution":
        session_cap = env_float("SESSION_MATURE_CHASE_SIZE_CAP_PCT", 0.65)
    elif severity == "hard_negative" and not enforce_session_momentum_gate:
        session_cap = env_float("SESSION_HARD_NEGATIVE_SIZE_CAP_PCT", 0.65)
    if session_cap is not None:
        apply_size_cap(
            account_state,
            cap_pct=session_cap,
            state_key="session_momentum_size_cap",
            payload={"severity": severity, "cap_pct": session_cap},
        )
        log.info(f"Session momentum size cap for {symbol}: severity={severity} → {session_cap}%")

    late_chase_gate = _late_chase_entry_risk(
        account_state=account_state,
        setup_obs=setup_obs,
    )
    account_state["late_chase_entry_gate"] = late_chase_gate
    unclassified_extended = (
        str(late_chase_gate.get("setup_label") or "").lower() == "unclassified_transition"
        and late_chase_gate.get("session_distance_from_vwap_pct") is not None
        and float(late_chase_gate.get("session_distance_from_vwap_pct") or 0)
        >= env_float("UNCLASSIFIED_EXTENDED_VWAP_CAP_PCT", 1.50)
    )
    if late_chase_gate.get("triggered"):
        cap_pct = float(late_chase_gate.get("cap_pct") or 0.50)
        apply_size_cap(
            account_state,
            cap_pct=cap_pct,
            state_key="late_chase_size_cap",
            payload={**late_chase_gate, "cap_pct": cap_pct},
        )
        log.warning(
            f"Late-chase entry cap for {symbol}: cap={cap_pct}% "
            f"reason={late_chase_gate.get('reason')} "
            f"setup={late_chase_gate.get('setup_label')} "
            f"ext={late_chase_gate.get('extension_from_recent_base_pct')} "
            f"vwap={late_chase_gate.get('session_distance_from_vwap_pct')}"
        )

    if unclassified_extended:
        cap_pct = env_float("UNCLASSIFIED_EXTENDED_SIZE_CAP_PCT", 0.35)
        apply_size_cap(
            account_state,
            cap_pct=cap_pct,
            state_key="unclassified_extended_size_cap",
            payload={
                **late_chase_gate,
                "cap_pct": cap_pct,
                "reason": "unclassified_transition extended above VWAP",
            },
        )
        log.warning(
            f"Unclassified extended entry cap for {symbol}: cap={cap_pct}% "
            f"vwap={late_chase_gate.get('session_distance_from_vwap_pct')}"
        )

    if unclassified_extended and float(
        late_chase_gate.get("session_distance_from_vwap_pct") or 0
    ) >= env_float("UNCLASSIFIED_EXTREME_VWAP_BLOCK_PCT", 2.25):
        reason = (
            "unclassified extended entry blocked: "
            f"vwap_dist={late_chase_gate.get('session_distance_from_vwap_pct')}; "
            f"setup_score={late_chase_gate.get('setup_score')}"
        )
        return StageOutcome(
            rejected=True,
            approval=deterministic_rejection(
                category="unclassified_extended_entry",
                reason=reason,
                metadata=late_chase_gate,
            ),
        )

    if late_chase_gate.get("would_block"):
        reason = (
            f"late-chase entry blocked: {late_chase_gate.get('reason')}; "
            f"setup={late_chase_gate.get('setup_label')}; "
            f"setup_score={late_chase_gate.get('setup_score')}; "
            f"extension={late_chase_gate.get('extension_from_recent_base_pct')}; "
            f"vwap_dist={late_chase_gate.get('session_distance_from_vwap_pct')}; "
            f"15m={late_chase_gate.get('session_momentum_15m_pct')}; "
            f"30m={late_chase_gate.get('session_momentum_30m_pct')}"
        )
        return StageOutcome(
            rejected=True,
            approval=deterministic_rejection(
                category="late_chase_entry",
                reason=reason,
                metadata=late_chase_gate,
            ),
        )

    return StageOutcome()


def run_intra_session_tape_degradation_gate(
    *,
    symbol: str,
    action: str,
    account_state: dict[str, Any],
    enabled: bool,
    start_hour_et: int,
    min_setup_score: float,
    et_timezone: Any,
    log: Any,
) -> StageOutcome:
    if action != "buy" or not enabled:
        return StageOutcome()

    try:
        tape_now_et = datetime.now(timezone.utc).astimezone(et_timezone)
        setup_obs = account_state.get("setup_observation") or {}
        session_label = (account_state.get("session_momentum") or {}).get("trend_label")
        setup_score_raw = setup_obs.get("setup_score")
        setup_score = float(setup_score_raw) if setup_score_raw is not None else None

        if (
            tape_now_et.hour >= start_hour_et
            and session_label in ("fading", "downtrend")
            and (setup_score is None or setup_score < min_setup_score)
        ):
            reason = (
                f"session_label={session_label}; "
                f"setup_score={setup_score}; "
                f"min_setup_score={min_setup_score}; "
                f"start_hour_et={start_hour_et}"
            )
            account_state["intra_session_tape_degradation"] = {
                "would_block": True,
                "reason": reason,
                "setup_score": setup_score,
                "min_setup_score": min_setup_score,
                "session_label": session_label,
            }
            return StageOutcome(
                rejected=True,
                approval=deterministic_rejection(
                    category="intra_session_tape_degradation",
                    reason=reason,
                    metadata=account_state["intra_session_tape_degradation"],
                ),
            )

        account_state["intra_session_tape_degradation"] = {
            "would_block": False,
            "setup_score": setup_score,
            "min_setup_score": min_setup_score,
            "session_label": session_label,
        }
    except Exception as exc:
        log.warning(f"Intra-session tape degradation gate skipped for {symbol}: {exc}")
        account_state["intra_session_tape_degradation_error"] = str(exc)

    return StageOutcome()


def run_final_approval_gates(
    *,
    signal: dict[str, Any],
    symbol: str,
    action: str,
    price: Any,
    account_state: dict[str, Any],
    context_runtime: Any,
    score_buy_opportunity: Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]],
    memory_for_signal: Callable[[str, dict[str, Any]], dict[str, Any]],
    build_intelligence_context: Callable[..., dict[str, Any]],
    evaluate_decision_policy: Callable[..., dict[str, Any]],
    public_decision_policy_config: Callable[[], dict[str, Any]],
    decision_policy_live_authority_enabled: Callable[[], bool],
    decision_policy_live_block_enabled: bool,
    decision_policy_live_size_down_enabled: bool,
    build_conviction_stack: Callable[..., Any],
    ml_prediction_bucket: Callable[[Any], str],
    compute_dominant_limiter: Callable[..., Any],
    log_event: Callable[..., Any],
    log: Any,
) -> ApprovalGateOutcome:
    claude_account_state = dict(account_state)

    if action == "buy":
        try:
            buying_power_for_affordability = float(account_state.get("buying_power") or 0)
            signal_price_f = float(price or 0)

            if (
                buying_power_for_affordability > 0
                and signal_price_f > 0
                and buying_power_for_affordability < signal_price_f
            ):
                reason = (
                    f"buying_power ${buying_power_for_affordability:.2f} cannot buy 1 share "
                    f"at signal price ${signal_price_f:.2f}"
                )
                return ApprovalGateOutcome(
                    rejected=True,
                    approval=deterministic_rejection(
                        category="affordability",
                        reason=reason,
                        metadata={
                            "buying_power": buying_power_for_affordability,
                            "signal_price": signal_price_f,
                        },
                    ),
                    claude_account_state=claude_account_state,
                )

        except Exception as exc:
            log.warning(f"Affordability gate skipped for {symbol} BUY due to error: {exc}")

    if action == "buy":
        opportunity = score_buy_opportunity(symbol, signal, account_state)
        account_state["opportunity_score"] = opportunity
        account_state["opportunity_score_0_100"] = opportunity
        claude_account_state["opportunity_score"] = opportunity
        claude_account_state["opportunity_score_0_100"] = opportunity

        strategy_memory = memory_for_signal(
            symbol,
            {
                "opportunity_score": opportunity,
                "opportunity_score_0_100": opportunity,
                "buy_opportunity": account_state.get("buy_opportunity") or {},
                "setup_observation": account_state.get("setup_observation") or {},
                "setup_quality": account_state.get("setup_quality") or {},
                "setup_quality_outcome": account_state.get("setup_quality_outcome") or {},
                "prediction_gate": account_state.get("prediction_gate") or {},
                "session_momentum": account_state.get("session_momentum") or {},
            },
        )
        account_state["strategy_memory"] = strategy_memory
        claude_account_state["strategy_memory"] = strategy_memory

        learned_min_score = strategy_memory.get("min_setup_score")
        if isinstance(learned_min_score, int):
            raw_score = opportunity.get("score")
            try:
                score_f = float(raw_score)
            except Exception:
                score_f = None

            normalized_score = score_f

            log.info(
                f"STRATEGY_MEMORY {symbol} BUY: "
                f"recommendation={strategy_memory.get('recommendation')} "
                f"learned_min_score={learned_min_score} "
                f"opportunity_score={raw_score} "
                f"normalized_score={normalized_score} "
                f"reason={strategy_memory.get('reason')}"
            )

            if (
                normalized_score is not None
                and strategy_memory.get("recommendation") in ("caution", "avoid")
                and normalized_score < learned_min_score
            ):
                reason = (
                    f"strategy memory tightened {symbol}: "
                    f"recommendation={strategy_memory.get('recommendation')} "
                    f"normalized_score={normalized_score:.1f} < learned_min_score={learned_min_score}; "
                    f"{strategy_memory.get('reason')}"
                )
                log.warning(f"Strategy memory gate blocked {symbol} BUY before Claude: {reason}")
                return ApprovalGateOutcome(
                    rejected=True,
                    approval=strategy_memory_rejection(
                        reason,
                        metadata={
                            "strategy_memory": strategy_memory,
                            "opportunity_score": opportunity,
                        },
                    ),
                    claude_account_state=claude_account_state,
                )

        log.info(
            f"Opportunity score for {symbol} BUY: "
            f"score={opportunity.get('score')} bucket={opportunity.get('bucket')} "
            f"decision={opportunity.get('decision')} "
            f"size_multiplier={opportunity.get('size_multiplier')} "
            f"reasons={opportunity.get('reason_codes')}"
        )

        if opportunity.get("decision") == "block":
            reason = opportunity.get("summary", "opportunity score blocked setup")
            log.warning(f"Opportunity score gate blocked {symbol} BUY before Claude: {reason}")
            return ApprovalGateOutcome(
                rejected=True,
                approval=opportunity_score_rejection(reason, metadata=opportunity),
                claude_account_state=claude_account_state,
            )

    intelligence_context = build_intelligence_context(
        symbol=symbol,
        action=action,
        account_state=account_state,
    )
    account_state["intelligence_context"] = intelligence_context
    claude_account_state["intelligence_context"] = intelligence_context

    summary = intelligence_context.get("summary") or {}
    log.info(
        f"INTELLIGENCE_CONTEXT {symbol} {action.upper()}: "
        f"recommended_action={summary.get('recommended_action')} "
        f"supports={summary.get('support_count')} "
        f"risks={summary.get('risk_count')} "
        f"primary_supports={summary.get('primary_supports')} "
        f"primary_risks={summary.get('primary_risks')}"
    )

    if action == "buy":
        advisory_cap = _advisory_feature_size_cap(account_state)
        account_state["advisory_feature_size_gate"] = advisory_cap
        claude_account_state["advisory_feature_size_gate"] = advisory_cap
        if advisory_cap.get("triggered"):
            cap_pct = float(advisory_cap.get("cap_pct") or 1.0)
            existing = account_state.get("max_position_size_pct_override")
            account_state["max_position_size_pct_override"] = (
                min(float(existing), cap_pct) if existing is not None else cap_pct
            )
            account_state["advisory_feature_size_cap"] = advisory_cap
            claude_account_state["advisory_feature_size_cap"] = advisory_cap
            claude_account_state["advisory_feature_max_position_size_pct"] = account_state[
                "max_position_size_pct_override"
            ]
            log.warning(
                f"Advisory feature size cap for {symbol}: "
                f"source={advisory_cap.get('source')} cap={cap_pct}% "
                f"reason={advisory_cap.get('reason')}"
            )

    decision_policy = evaluate_decision_policy(
        symbol=symbol,
        action=action,
        intelligence_context=intelligence_context,
        account_state=account_state,
    )
    account_state["decision_policy"] = decision_policy
    claude_account_state["decision_policy"] = decision_policy
    decision_policy_config = public_decision_policy_config()
    account_state["decision_policy_authority"] = decision_policy_config
    claude_account_state["decision_policy_authority"] = decision_policy_config

    log.info(
        f"DECISION_POLICY {symbol} {action.upper()}: "
        f"decision={decision_policy.get('decision')} "
        f"size_multiplier={decision_policy.get('size_multiplier')} "
        f"reason={decision_policy.get('reason')} "
        f"risks={decision_policy.get('risks')} "
        f"supports={decision_policy.get('supports')}"
    )

    decision_policy_authority_enabled = decision_policy_live_authority_enabled()
    decision_policy_live_block = (
        decision_policy_live_block_enabled and decision_policy_authority_enabled
    )
    decision_policy_live_size_down = (
        decision_policy_live_size_down_enabled and decision_policy_authority_enabled
    )
    account_state["decision_policy_outcome"] = {
        "advisory_decision": decision_policy.get("decision"),
        "authority_mode": decision_policy_config.get("authority_mode"),
        "enforced": False,
        "effect_on_size": "none",
        "effect_on_execution": "none",
        "reason": decision_policy.get("reason"),
    }
    claude_account_state["decision_policy_outcome"] = account_state["decision_policy_outcome"]

    if (
        action == "buy"
        and decision_policy_live_block
        and decision_policy.get("decision") == "block"
    ):
        account_state["decision_policy_outcome"]["enforced"] = True
        account_state["decision_policy_outcome"]["effect_on_execution"] = "block"
        claude_account_state["decision_policy_outcome"] = account_state["decision_policy_outcome"]
        reason = decision_policy.get("reason", "decision policy blocked setup")
        log.warning(f"Decision policy gate blocked {symbol} BUY before Claude: {reason}")
        return ApprovalGateOutcome(
            rejected=True,
            approval=decision_policy_rejection(reason, metadata=decision_policy),
            claude_account_state=claude_account_state,
        )
    elif action == "buy" and decision_policy.get("decision") == "block":
        log.warning(
            f"Decision policy block observed but not enforced for {symbol} BUY: "
            f"authority_enabled={decision_policy_authority_enabled} "
            f"live_block_enabled={decision_policy_live_block_enabled} "
            f"mode={decision_policy_config.get('authority_mode')} "
            f"reason={decision_policy.get('reason')}"
        )

    if (
        action == "buy"
        and decision_policy_live_size_down
        and decision_policy.get("decision") == "size_down"
    ):
        try:
            size_multiplier = float(decision_policy.get("size_multiplier") or 1.0)
        except Exception:
            size_multiplier = 1.0

        size_multiplier = max(0.0, min(1.0, size_multiplier))

        current_limit = None
        for key in ("max_position_size_pct", "position_size_pct"):
            try:
                val = claude_account_state.get(key)
                if val is not None:
                    current_limit = float(val)
                    break
            except Exception:
                pass

        if current_limit is None:
            current_limit = 2.0

        reduced_limit = round(current_limit * size_multiplier, 4)

        account_state["decision_policy_size_down"] = {
            "enabled": True,
            "original_position_size_pct": current_limit,
            "reduced_position_size_pct": reduced_limit,
            "size_multiplier": size_multiplier,
            "reason": decision_policy.get("reason"),
        }
        claude_account_state["decision_policy_size_down"] = account_state[
            "decision_policy_size_down"
        ]
        account_state["decision_policy_outcome"]["enforced"] = True
        account_state["decision_policy_outcome"]["effect_on_size"] = "size_down"
        claude_account_state["decision_policy_outcome"] = account_state["decision_policy_outcome"]
        claude_account_state["max_position_size_pct"] = reduced_limit
        claude_account_state["decision_policy_max_position_size_pct"] = reduced_limit

        log.warning(
            f"DECISION_POLICY_SIZE_DOWN {symbol} BUY: "
            f"original_position_size_pct={current_limit} "
            f"size_multiplier={size_multiplier} "
            f"reduced_position_size_pct={reduced_limit} "
            f"reason={decision_policy.get('reason')}"
        )

        log_event(
            event_type="DECISION_POLICY_SIZE_DOWN",
            symbol=symbol,
            action=action,
            decision="size_down",
            severity="medium",
            reason=decision_policy.get("reason"),
            source="app.py",
            payload={
                "decision_policy": decision_policy,
                "original_position_size_pct": current_limit,
                "reduced_position_size_pct": reduced_limit,
                "size_multiplier": size_multiplier,
            },
        )
    elif action == "buy" and decision_policy.get("decision") == "size_down":
        log.info(
            f"Decision policy size_down observed but not enforced for {symbol} BUY: "
            f"authority_enabled={decision_policy_authority_enabled} "
            f"live_size_down_enabled={decision_policy_live_size_down_enabled} "
            f"mode={decision_policy_config.get('authority_mode')} "
            f"reason={decision_policy.get('reason')}"
        )

    if action == "buy":
        build_conviction_stack(
            action=action,
            account_state=account_state,
            ml_prediction_bucket=ml_prediction_bucket,
            compute_dominant_limiter=compute_dominant_limiter,
        )

    built_context = context_runtime.refresh(
        intelligence_context=intelligence_context,
        claude_account_state=claude_account_state,
    )
    claude_account_state = built_context.claude_account_state

    summary = built_context.summary
    log.info(
        f"Decision context for {symbol} {action.upper()}: "
        f"setup={summary.get('setup_label')}/"
        f"{summary.get('setup_policy_action')} "
        f"prediction={summary.get('prediction_score')}/"
        f"{summary.get('prediction_decision')} "
        f"session={summary.get('session_trend_label')}/"
        f"{summary.get('session_trend_score')} "
        f"session_gate={summary.get('session_gate_severity')}/"
        f"{summary.get('session_gate_would_block')} "
        f"effective_bias={summary.get('effective_bias')}"
    )

    if action == "buy":
        log.info(
            f"Conviction stack for {symbol} BUY: "
            f"buy_opp={account_state['conviction_stack']['buy_opportunity']} "
            f"strategy={account_state['conviction_stack']['strategy_score']:.0f} "
            f"session={account_state['conviction_stack']['session_severity']} "
            f"ml_bucket={account_state['conviction_stack']['ml_bucket']} "
            f"cap={account_state['conviction_stack']['effective_cap_pct']} "
            f"dominant={account_state['dominant_limiter']}"
        )

    return ApprovalGateOutcome(claude_account_state=claude_account_state)
