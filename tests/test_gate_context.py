#!/usr/bin/env python3
"""Unit tests for DecisionTrace and GateContext."""

from __future__ import annotations

# ruff: noqa: E402
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.signals.context.account_state_view import AccountStateView
from trading_bot.signals.live.gate_context import DecisionTrace, GateContext

# ---------------------------------------------------------------------------
# DecisionTrace
# ---------------------------------------------------------------------------


def test_decision_trace_records_and_retrieves():
    trace = DecisionTrace()
    trace.record("ml_authority", {"allowed": True})
    trace.record("conviction_stack", {"score": 7.5})
    d = trace.as_dict()
    assert d["ml_authority"] == {"allowed": True}
    assert d["conviction_stack"] == {"score": 7.5}


def test_decision_trace_last_write_wins():
    trace = DecisionTrace()
    trace.record("key", "first")
    trace.record("key", "second")
    assert trace.as_dict()["key"] == "second"


def test_decision_trace_len_and_contains():
    trace = DecisionTrace()
    assert len(trace) == 0
    assert "key" not in trace
    trace.record("key", 42)
    assert len(trace) == 1
    assert "key" in trace


def test_decision_trace_as_dict_is_snapshot():
    trace = DecisionTrace()
    trace.record("a", 1)
    snap = trace.as_dict()
    trace.record("b", 2)
    assert "b" not in snap  # snapshot is decoupled from live state


def test_decision_trace_empty_on_init():
    trace = DecisionTrace()
    assert trace.as_dict() == {}
    assert len(trace) == 0


# ---------------------------------------------------------------------------
# GateContext
# ---------------------------------------------------------------------------


def test_gate_context_intelligence_is_zero_copy():
    account_state: dict = {"symbol": "AAPL", "action": "buy"}
    ctx = GateContext(
        intelligence=AccountStateView.from_account_state(account_state),
        trace=DecisionTrace(),
        symbol="AAPL",
        action="buy",
        price=150.0,
        dedupe_key="key-1",
    )
    # Mutations to the underlying dict are visible through the view
    account_state["regime_circuit_breaker"] = {"status": "ok"}
    assert ctx.intelligence.get("regime_circuit_breaker") == {"status": "ok"}
    assert ctx.intelligence.raw is account_state


def test_gate_context_defaults_are_none_and_empty():
    ctx = GateContext(
        intelligence=AccountStateView.from_account_state({}),
        trace=DecisionTrace(),
        symbol="NVDA",
        action="buy",
        price=None,
        dedupe_key=None,
    )
    assert ctx.current_et is None
    assert ctx.existing_position is None
    assert ctx.macro_risk == {}
    assert ctx.bias_entry == {}
    assert ctx.decision == {}
    assert ctx.rejection_adapter is None


def test_gate_context_mutable_locals_update_in_order():
    account_state: dict = {"symbol": "NVDA", "action": "buy"}
    ctx = GateContext(
        intelligence=AccountStateView.from_account_state(account_state),
        trace=DecisionTrace(),
        symbol="NVDA",
        action="buy",
        price=900.0,
        dedupe_key="d-1",
    )

    # Phase 1: preflight locals
    ctx.current_et = "09:31"
    ctx.existing_position = {"qty": 5, "avg_entry": 895.0}
    assert ctx.current_et == "09:31"
    assert ctx.existing_position["qty"] == 5

    # Phase 2: macro hydration
    ctx.macro_risk = {"risk_level": "low", "macro_score": 3}
    assert ctx.macro_risk["risk_level"] == "low"

    # Phase 3: bias entry
    ctx.bias_entry = {"direction": "bullish"}
    assert ctx.bias_entry["direction"] == "bullish"

    # Phase 4: claude decision
    ctx.decision = {"approved": True, "confidence": "high"}
    assert ctx.decision["approved"] is True


def test_gate_context_scalar_fields():
    ctx = GateContext(
        intelligence=AccountStateView.from_account_state({}),
        trace=DecisionTrace(),
        symbol="AAPL",
        action="sell",
        price=175.25,
        dedupe_key="sell-dedupe-abc",
    )
    assert ctx.symbol == "AAPL"
    assert ctx.action == "sell"
    assert ctx.price == 175.25
    assert ctx.dedupe_key == "sell-dedupe-abc"


def test_gate_context_trace_records_independently():
    account_state: dict = {}
    ctx = GateContext(
        intelligence=AccountStateView.from_account_state(account_state),
        trace=DecisionTrace(),
        symbol="META",
        action="buy",
        price=500.0,
        dedupe_key=None,
    )
    ctx.trace.record("ml_authority", {"mode": "paper_only", "allowed": False})
    ctx.trace.record("session_gate_outcome", {"passed": True})
    d = ctx.trace.as_dict()
    assert d["ml_authority"]["mode"] == "paper_only"
    assert d["session_gate_outcome"]["passed"] is True
    # trace does not touch account_state
    assert "ml_authority" not in account_state


def main():
    tests = [
        test_decision_trace_records_and_retrieves,
        test_decision_trace_last_write_wins,
        test_decision_trace_len_and_contains,
        test_decision_trace_as_dict_is_snapshot,
        test_decision_trace_empty_on_init,
        test_gate_context_intelligence_is_zero_copy,
        test_gate_context_defaults_are_none_and_empty,
        test_gate_context_mutable_locals_update_in_order,
        test_gate_context_scalar_fields,
        test_gate_context_trace_records_independently,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} gate-context tests passed.")


if __name__ == "__main__":
    main()
