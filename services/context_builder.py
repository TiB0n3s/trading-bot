"""Context-building stage interfaces and legacy extraction helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from services.signal_models import DecisionContext, SignalContext


@dataclass(frozen=True)
class SetupObservation:
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PredictionObservation:
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class SessionMomentumObservation:
    data: dict[str, Any] = field(default_factory=dict)
    gate: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class StrategyObservation:
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class MarketAlignmentObservation:
    data: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class BuiltSignalContext:
    account_state: dict[str, Any]
    decision_context: dict[str, Any]
    setup: SetupObservation
    prediction: PredictionObservation
    session: SessionMomentumObservation
    strategy: StrategyObservation
    market_alignment: MarketAlignmentObservation
    claude_account_state: dict[str, Any]
    summary: dict[str, Any]


def build_claude_account_state(account_state: dict[str, Any]) -> dict[str, Any]:
    claude_account_state = dict(account_state)
    adaptive_confirmation = account_state.get("adaptive_buy_confirmation") or {}
    market_alignment = account_state.get("market_alignment") or {}
    claude_account_state.pop("adaptive_buy_confirmation", None)
    claude_account_state.pop("adaptive_buy_confirmation_error", None)
    claude_account_state.pop("market_alignment", None)
    claude_account_state.pop("market_alignment_error", None)
    claude_account_state["market_context_summary"] = {
        "required_confirmations": adaptive_confirmation.get("required_buy_confirmations"),
        "confirmation_reasons": adaptive_confirmation.get("reasons"),
        "market_aligned": market_alignment.get("aligned_for_buy"),
        "alignment_reason": market_alignment.get("reason"),
    }
    return claude_account_state


def build_final_signal_context(
    *,
    account_state: dict[str, Any],
    trend_table: dict[str, Any],
    intelligence_context: dict[str, Any] | None = None,
    claude_account_state: dict[str, Any] | None = None,
) -> BuiltSignalContext:
    account_state["trend_table"] = trend_table

    setup = account_state.get("setup_observation") or {}
    prediction = account_state.get("prediction_gate") or {}
    session = account_state.get("session_momentum") or {}
    session_gate = account_state.get("session_momentum_gate") or {}
    strategy = account_state.get("strategy_observation") or {}
    market_alignment = account_state.get("market_alignment") or {}
    intelligence_context = intelligence_context or account_state.get("intelligence_context") or {}
    claude_account_state = build_claude_account_state(account_state)

    decision_context = {
        "setup": setup,
        "prediction": prediction,
        "session_momentum": session,
        "session_momentum_gate": session_gate,
        "strategy": strategy,
        "market_alignment": market_alignment,
        "intelligence_context": intelligence_context,
    }

    summary = {
        "setup_label": setup.get("setup_label"),
        "setup_policy_action": setup.get("setup_policy_action"),
        "prediction_score": prediction.get("prediction_score"),
        "prediction_decision": prediction.get("prediction_decision"),
        "session_trend_label": session.get("trend_label"),
        "session_trend_score": session.get("trend_score"),
        "session_gate_severity": session_gate.get("severity"),
        "session_gate_would_block": session_gate.get("would_block"),
        "effective_bias": account_state.get("market_bias_effective"),
    }

    return BuiltSignalContext(
        account_state=account_state,
        decision_context=decision_context,
        setup=SetupObservation(setup),
        prediction=PredictionObservation(prediction),
        session=SessionMomentumObservation(session, session_gate),
        strategy=StrategyObservation(strategy),
        market_alignment=MarketAlignmentObservation(market_alignment),
        claude_account_state=claude_account_state,
        summary=summary,
    )


class ContextBuilder:
    def build(self, signal: SignalContext) -> DecisionContext:
        return DecisionContext(signal=signal)
