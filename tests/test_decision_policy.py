#!/usr/bin/env python3
"""Decision policy authority and safety tests."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import decision_policy


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy value")


def assert_lte(actual, expected, label):
    if actual > expected:
        raise AssertionError(f"{label}: expected <= {expected!r}, got {actual!r}")


def neutral_memory(symbol, intelligence_context=None, **kwargs):
    return {"available": True, "matches": []}


def avoid_memory(symbol, intelligence_context=None, **kwargs):
    return {
        "available": True,
        "matches": [
            {
                "label": "symbol",
                "recommendation": "avoid",
                "min_setup_score": 80,
                "reason": "test avoid memory",
            }
        ],
    }


def test_hard_gate_context_can_only_block():
    result = decision_policy.evaluate_decision_policy(
        "AAPL",
        "buy",
        intelligence_context={"summary": {"recommended_action": "allow"}},
        account_state={"macro_risk": {"block_new_buys": True}},
    )

    assert_equal(result["decision"], "block", "decision")
    assert_equal(result["size_multiplier"], 0.0, "size multiplier")
    assert_equal(result["authority_scope"], "hard_gate_mirror_for_replay_audit", "authority scope")
    assert_equal(result["can_increase_size"], False, "can increase size")
    assert_equal(result["can_submit_orders"], False, "can submit orders")


def test_policy_never_increases_size(monkeypatch=None):
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = avoid_memory
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 16, "decision": "allow"},
            },
            account_state={},
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_true(result["decision"] in {"block", "size_down", "allow"}, "known decision")
    assert_lte(float(result["size_multiplier"]), 1.0, "size multiplier")
    assert_equal(result["can_increase_size"], False, "can increase size")


def test_sell_signals_pass_through_without_order_authority():
    result = decision_policy.evaluate_decision_policy("AAPL", "sell")

    assert_equal(result["decision"], "allow", "sell decision")
    assert_equal(result["size_multiplier"], 1.0, "sell size multiplier")
    assert_equal(result.get("can_submit_orders"), False, "can submit orders")


def test_decision_policy_module_does_not_import_order_execution():
    source = inspect.getsource(decision_policy)

    assert_true("place_order(" not in source, "place_order call not referenced")
    assert_true("submit_order(" not in source, "submit_order call not referenced")
    assert_true("from broker import" not in source, "broker not imported")


if __name__ == "__main__":
    test_hard_gate_context_can_only_block()
    print("[OK] test_hard_gate_context_can_only_block")
    test_policy_never_increases_size()
    print("[OK] test_policy_never_increases_size")
    test_sell_signals_pass_through_without_order_authority()
    print("[OK] test_sell_signals_pass_through_without_order_authority")
    test_decision_policy_module_does_not_import_order_execution()
    print("[OK] test_decision_policy_module_does_not_import_order_execution")
    print("\nAll 4 decision policy tests passed.")
