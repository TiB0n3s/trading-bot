"""Canonical decision trace engine used by runtime compatibility paths."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from services.decision.gates import (
    build_cash_safe_gate,
    build_claude_gate,
    build_decision_policy_gate,
    build_execution_gate,
    build_intelligence_adjudication,
    build_macro_gate,
    build_ml_authority_gate,
    build_prediction_gate,
    build_preflight_gate,
    build_session_gate,
    build_setup_gate,
    build_sizing_gate,
    build_trend_gate,
)
from src.trading_bot.intelligence.adjudicator import ModelAdjudication
from src.trading_bot.runtime.authority import AuthorityMatrix
from src.trading_bot.runtime.gate_engine import CallableGate, GateEngine
from src.trading_bot.runtime.trace import DecisionTrace, GateResult


def _authority_level(execution_mode: str) -> str:
    return "paper" if execution_mode in {"paper", "dry_run"} else "live"


@dataclass(frozen=True)
class DecisionEvaluation:
    trace: DecisionTrace
    adjudication: ModelAdjudication

    def to_dict(self) -> dict[str, Any]:
        return {
            "trace": self.trace.to_dict(),
            "adjudication": self.adjudication.to_dict(),
        }


class DecisionEngine:
    """Evaluate canonical decision metadata without submitting orders."""

    def __init__(self, authority_matrix: AuthorityMatrix | None = None):
        self.authority = authority_matrix or AuthorityMatrix()

    def evaluate(
        self,
        *,
        account_state: dict[str, Any],
        decision: dict[str, Any],
        source: str,
        execution_mode: str,
        exploration: dict[str, Any] | None = None,
    ) -> DecisionEvaluation:
        adjudication = build_intelligence_adjudication(
            account_state=account_state,
            intelligence_context=account_state.get("intelligence_context") or {},
        )

        def adjudication_gate(_state: dict[str, Any]) -> GateResult:
            effect = adjudication.recommended_effect
            if effect == "block":
                decision_value = "block"
            elif effect == "size_down":
                decision_value = "cap"
            elif effect in {"approve", "increase_size"}:
                decision_value = "pass"
            else:
                decision_value = "observe"
            return GateResult(
                gate_id="intelligence_adjudicator",
                layer="intelligence",
                decision=decision_value,
                authority="none",
                enforced=False,
                reason=f"{adjudication.direction}/{adjudication.recommended_effect}",
                inputs={
                    "setup_quality": account_state.get("setup_quality"),
                    "buy_opportunity": account_state.get("buy_opportunity"),
                    "prediction_gate": account_state.get("prediction_gate"),
                },
                outputs=adjudication.to_dict(),
            )

        def authority_gate(_state: dict[str, Any]) -> GateResult:
            if exploration and exploration.get("allowed"):
                action = (
                    "increase_size" if exploration.get("effect") == "size_increase" else "approve"
                )
                allowed = self.authority.can("paper_exploration", action, execution_mode)
                return GateResult(
                    gate_id="paper_exploration_authority",
                    layer="authority",
                    decision="cap" if action == "increase_size" else "pass",
                    authority=_authority_level(execution_mode),
                    enforced=allowed,
                    reason=exploration.get("reason") or "paper exploration authority",
                    size_cap_pct=exploration.get("position_size_pct"),
                    inputs=self.authority.decision(
                        "paper_exploration",
                        action,
                        execution_mode,
                    ),
                    outputs=exploration,
                )
            return GateResult(
                gate_id="paper_exploration_authority",
                layer="authority",
                decision="observe",
                authority="none",
                enforced=False,
                reason="no paper exploration authority change",
                inputs=self.authority.decision(
                    "paper_exploration",
                    "approve",
                    execution_mode,
                ),
            )

        def claude_gate(_state: dict[str, Any]) -> GateResult:
            return build_claude_gate(
                decision=decision,
                source=source,
                authority=_authority_level(execution_mode),
            )

        trace = GateEngine(
            [
                CallableGate(
                    "preflight", "preflight", lambda _state: build_preflight_gate(account_state)
                ),
                CallableGate(
                    "cash_safe", "risk", lambda _state: build_cash_safe_gate(account_state)
                ),
                CallableGate("macro", "macro", lambda _state: build_macro_gate(account_state)),
                CallableGate(
                    "setup_policy", "setup", lambda _state: build_setup_gate(account_state)
                ),
                CallableGate(
                    "trend_confirmation", "trend", lambda _state: build_trend_gate(account_state)
                ),
                CallableGate(
                    "prediction", "prediction", lambda _state: build_prediction_gate(account_state)
                ),
                CallableGate(
                    "session_momentum", "session", lambda _state: build_session_gate(account_state)
                ),
                CallableGate(
                    "ml_authority", "ml", lambda _state: build_ml_authority_gate(account_state)
                ),
                CallableGate(
                    "decision_policy",
                    "policy",
                    lambda _state: build_decision_policy_gate(account_state),
                ),
                CallableGate("intelligence_adjudicator", "intelligence", adjudication_gate),
                CallableGate("paper_exploration_authority", "authority", authority_gate),
                CallableGate(
                    "final_sizing", "sizing", lambda _state: build_sizing_gate(account_state)
                ),
                CallableGate(
                    "execution_quality",
                    "execution",
                    lambda _state: build_execution_gate(account_state),
                ),
                CallableGate("claude_approval", "approval", claude_gate),
            ]
        ).run({"final_decision": "approved" if bool(decision.get("approved")) else "rejected"})
        trace.shadow = {
            "claude_original_approved": bool(decision.get("approved")),
            "approval_source": source,
            "paper_exploration": exploration or {},
        }
        return DecisionEvaluation(trace=trace, adjudication=adjudication)

    def store_to_account_state(
        self,
        *,
        account_state: dict[str, Any],
        decision: dict[str, Any],
        source: str,
        execution_mode: str,
        exploration: dict[str, Any] | None = None,
    ) -> DecisionEvaluation:
        evaluation = self.evaluate(
            account_state=account_state,
            decision=decision,
            source=source,
            execution_mode=execution_mode,
            exploration=exploration,
        )
        trace_payload = evaluation.trace.to_dict()
        account_state["intelligence_adjudication"] = evaluation.adjudication.to_dict()
        account_state["decision_trace"] = trace_payload
        account_state["canonical_decision_trace"] = trace_payload
        return evaluation
