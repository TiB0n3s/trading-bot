#!/usr/bin/env python3
"""Runtime decision engine contract tests."""
# ruff: noqa: E402

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.approval_service import evaluate_approval_decision
from services.decision import CanonicalDecisionOrchestrator, DecisionEngine
from services.decision.adapters import auto_buy_candidate_from_raw, webhook_candidate_from_raw
from services.decision.authority import AuthorityMatrix, normalize_authority_mode
from services.decision.gates import build_intelligence_adjudication
from services.decision.state import DecisionState
from services.decision.trace import GateResult
from services.signal_models import (
    ExecutionResult,
    PipelineResult,
    SignalContext,
    SignalRuntimeState,
)
from src.trading_bot.runtime.gate_engine import CallableGate, GateEngine


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy value, got {value!r}")


def _strong_account_state() -> dict:
    return {
        "setup_quality": {
            "recommendation": "buy",
            "policy_action": "allow",
            "score": 88,
        },
        "buy_opportunity": {
            "buy_opportunity_recommendation": "strong_buy_candidate",
            "buy_opportunity_score": 13,
            "max_position_size_pct": 1.5,
        },
        "prediction_gate": {
            "deterministic_signal_quality_decision": "pass",
            "prediction_score": 72,
            "prediction_sample_size": 5000,
        },
        "session_momentum_gate": {"severity": "pass"},
        "execution_quality": {"decision": "allow"},
    }


def test_authority_matrix_standardizes_runtime_permissions():
    matrix = AuthorityMatrix()
    assert_equal(normalize_authority_mode("hard"), "live_block", "hard alias")
    assert_equal(normalize_authority_mode("observe_only"), "observe", "observe alias")
    assert_equal(matrix.can("paper_exploration", "approve", "paper"), True, "paper approve")
    assert_equal(
        matrix.can("paper_exploration", "increase_size", "cash_full"),
        False,
        "live size increase",
    )
    assert_equal(matrix.can("deterministic_risk", "block", "cash_full"), True, "risk block")


def test_gate_engine_records_ordered_trace_and_caps():
    trace = GateEngine(
        [
            CallableGate(
                "model_score",
                "intelligence",
                lambda _state: GateResult(
                    gate_id="model_score",
                    layer="intelligence",
                    decision="pass",
                    reason="supportive",
                ),
            ),
            CallableGate(
                "liquidity_stress",
                "risk",
                lambda _state: GateResult(
                    gate_id="liquidity_stress",
                    layer="risk",
                    decision="cap",
                    authority="paper",
                    enforced=True,
                    reason="stress cap",
                    size_cap_pct=0.5,
                ),
            ),
        ]
    ).run({"final_decision": "approved"})

    payload = trace.to_dict()
    assert_equal(payload["final_decision"], "approved", "final decision")
    assert_equal(payload["dominant_limiter"], "liquidity_stress", "dominant limiter")
    assert_equal(payload["active_caps"][0]["size_cap_pct"], 0.5, "size cap")
    assert_equal(payload["gate_results"][0]["gate_id"], "model_score", "gate order")


def test_decision_state_serializes_to_legacy_account_state():
    state = DecisionState(
        signal={"symbol": "AAPL", "action": "buy"},
        setup={"score": 90},
        prediction={"prediction_score": 70},
        trace={"trace_version": "decision_trace_v1"},
    )
    legacy = state.to_legacy_account_state()
    assert_equal(legacy["setup_quality"]["score"], 90, "setup bridge")
    assert_equal(legacy["prediction_gate"]["prediction_score"], 70, "prediction bridge")
    assert_equal(legacy["decision_trace"]["trace_version"], "decision_trace_v1", "trace bridge")


def test_signal_candidates_normalize_webhook_and_auto_buy():
    webhook = webhook_candidate_from_raw({"symbol": "aapl", "action": "BUY", "price": "325.50"})
    auto_buy = auto_buy_candidate_from_raw(
        {
            "symbol": "msft",
            "close": "412.25",
            "candidate_id": "candidate-1",
            "setup_score": 91,
        }
    )
    assert_equal(webhook.symbol, "AAPL", "webhook symbol")
    assert_equal(webhook.action, "buy", "webhook action")
    assert_equal(webhook.to_legacy_signal()["price"], 325.5, "webhook price")
    assert_equal(auto_buy.source, "auto_buy", "auto-buy source")
    assert_equal(auto_buy.to_legacy_signal()["setup_score"], 91, "auto-buy features")


def test_intelligence_adjudicator_aggregates_model_surfaces():
    adjudication = build_intelligence_adjudication(
        account_state=_strong_account_state(),
        intelligence_context={},
    )
    assert_equal(adjudication.direction, "support", "direction")
    assert_equal(adjudication.confidence, "high", "confidence")
    assert_equal(adjudication.recommended_effect, "approve", "effect")
    assert_equal(adjudication.sample_size, 5000, "sample size")


def test_decision_engine_stores_canonical_trace_directly():
    account_state = _strong_account_state()
    evaluation = DecisionEngine().store_to_account_state(
        account_state=account_state,
        decision={
            "approved": True,
            "confidence": "high",
            "reason": "canonical engine approved",
            "position_size_pct": 1.0,
        },
        source="claude",
        execution_mode="paper",
    )
    assert_equal(evaluation.trace.final_decision, "approved", "evaluation final")
    assert_equal(
        account_state["canonical_decision_trace"]["shadow"]["approval_source"],
        "claude",
        "stored source",
    )
    assert_equal(
        account_state["intelligence_adjudication"]["recommended_effect"],
        "approve",
        "stored adjudication",
    )
    gate_ids = [row["gate_id"] for row in account_state["canonical_decision_trace"]["gate_results"]]
    for expected in (
        "preflight",
        "cash_safe",
        "macro",
        "setup_policy",
        "trend_confirmation",
        "prediction",
        "session_momentum",
        "ml_authority",
        "decision_policy",
        "intelligence_adjudicator",
        "paper_exploration_authority",
        "final_sizing",
        "execution_quality",
        "claude_approval",
    ):
        assert_true(expected in gate_ids, f"{expected} in full trace")


def test_decision_engine_marks_execution_quality_block_as_enforced():
    account_state = _strong_account_state()
    account_state["execution_quality"] = {
        "decision": "block",
        "reason": "spread and slippage too wide",
    }

    DecisionEngine().store_to_account_state(
        account_state=account_state,
        decision={
            "approved": True,
            "confidence": "high",
            "reason": "canonical engine approved",
            "position_size_pct": 1.0,
        },
        source="claude",
        execution_mode="paper",
    )

    execution_gate = next(
        row
        for row in account_state["canonical_decision_trace"]["gate_results"]
        if row["gate_id"] == "execution_quality"
    )
    assert_equal(execution_gate["decision"], "block", "execution gate decision")
    assert_equal(execution_gate["enforced"], True, "execution gate enforced")
    assert_equal(
        account_state["canonical_decision_trace"]["blocking_gate"],
        "execution_quality",
        "blocking gate",
    )


def test_canonical_orchestrator_owns_live_signal_handoff():
    class _CompatibilityProcessor:
        def __init__(self):
            self.calls = []

        def process(self, context, runtime_state, context_runtime, preflight_result):
            self.calls.append(
                {
                    "context": context,
                    "runtime_state": runtime_state,
                    "context_runtime": context_runtime,
                    "preflight_result": preflight_result,
                    "trace_present": bool(
                        runtime_state.account_state.get("canonical_decision_trace")
                    ),
                }
            )
            return PipelineResult(
                handled=True,
                context=context,
                execution=ExecutionResult(submitted=False, status="compatibility_delegate"),
            )

    processor = _CompatibilityProcessor()
    runtime_state = SignalRuntimeState(
        raw_signal={"symbol": "AAPL", "action": "buy", "price": 100.0},
        symbol="AAPL",
        action="buy",
        received_at=datetime.now(),
        account_state=_strong_account_state(),
    )
    context = SignalContext(
        raw_signal=runtime_state.raw_signal,
        symbol="AAPL",
        action="buy",
        price=100.0,
    )

    result = CanonicalDecisionOrchestrator(processor).process(
        context,
        runtime_state,
        context_runtime={"built": True},
        preflight_result={"allowed": True},
    )

    assert_equal(result.execution.status, "compatibility_delegate", "delegate status")
    assert_true(processor.calls[0]["trace_present"], "trace before delegate")
    assert_equal(
        runtime_state.account_state["canonical_orchestration_status"],
        "handled",
        "orchestration status",
    )
    assert_equal(
        runtime_state.decision_context["canonical_orchestrator"]["status"],
        "pre_trace_recorded",
        "decision context status",
    )


def test_claude_cannot_approve_cash_buy_without_authority():
    account_state = _strong_account_state()
    result = evaluate_approval_decision(
        signal={"symbol": "AAPL", "action": "buy"},
        action="buy",
        claude_account_state={},
        evaluate_signal=lambda *_: {
            "approved": True,
            "confidence": "high",
            "reason": "Claude approved",
            "position_size_pct": 1.0,
        },
        cash_safe_mode=False,
        market_bias={},
        account_state=account_state,
        medium_confidence_override=lambda **_: (True, "test override"),
        tape_exception_enabled=False,
        execution_mode="cash_full",
        ml_authority_config={},
    )
    assert_equal(result.approved, False, "approved")
    assert_equal(result.source, "authority_matrix", "source")
    assert_true("AuthorityMatrix denied claude approve authority" in result.reason, "reason")
    assert_equal(
        account_state["canonical_decision_trace"]["shadow"]["approval_source"],
        "authority_matrix",
        "trace source",
    )


def test_approval_path_stores_canonical_trace_for_paper_authority():
    account_state = _strong_account_state()
    result = evaluate_approval_decision(
        signal={"symbol": "AAPL", "action": "buy"},
        action="buy",
        claude_account_state={},
        evaluate_signal=lambda *_: {
            "approved": False,
            "confidence": "medium",
            "reason": "Claude cautious despite strong canonical evidence",
            "position_size_pct": 1.0,
        },
        cash_safe_mode=False,
        market_bias={},
        account_state=account_state,
        medium_confidence_override=lambda **_: (True, "test override"),
        tape_exception_enabled=False,
        execution_mode="paper",
        ml_authority_config={
            "paper_exploration_authority": {
                "enabled": True,
                "min_setup_score": 78,
                "min_buy_opportunity_score": 10,
                "min_prediction_score": 55,
                "size_lift_multiplier": 1.25,
                "max_position_size_pct": 1.5,
            }
        },
    )

    assert_equal(result.approved, True, "approved")
    assert_equal(result.source, "paper_exploration_authority", "source")
    assert_true(account_state.get("intelligence_adjudication"), "adjudication stored")
    trace = account_state["canonical_decision_trace"]
    assert_equal(trace["trace_version"], "decision_trace_v1", "trace version")
    assert_equal(trace["final_decision"], "approved", "trace final")
    gate_ids = [row["gate_id"] for row in trace["gate_results"]]
    assert_true("intelligence_adjudicator" in gate_ids, "intelligence gate")
    assert_true("paper_exploration_authority" in gate_ids, "authority gate")
    assert_true("claude_approval" in gate_ids, "claude gate")
    assert_equal(trace["shadow"]["approval_source"], "paper_exploration_authority", "trace source")


def main():
    tests = [
        test_authority_matrix_standardizes_runtime_permissions,
        test_gate_engine_records_ordered_trace_and_caps,
        test_decision_state_serializes_to_legacy_account_state,
        test_signal_candidates_normalize_webhook_and_auto_buy,
        test_intelligence_adjudicator_aggregates_model_surfaces,
        test_decision_engine_stores_canonical_trace_directly,
        test_decision_engine_marks_execution_quality_block_as_enforced,
        test_canonical_orchestrator_owns_live_signal_handoff,
        test_claude_cannot_approve_cash_buy_without_authority,
        test_approval_path_stores_canonical_trace_for_paper_authority,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} runtime decision engine contract tests passed.")


if __name__ == "__main__":
    main()
