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
        account_state = {}
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 16, "decision": "allow"},
            },
            account_state=account_state,
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_true(result["decision"] in {"block", "size_down", "allow"}, "known decision")
    assert_lte(float(result["size_multiplier"]), 1.0, "size multiplier")
    assert_equal(result["can_increase_size"], False, "can increase size")
    assert_true("utility_estimate" in result, "utility estimate present")
    assert_true("calibrated_confidence" in account_state, "calibrated confidence present")
    assert_equal(
        account_state["calibrated_confidence"]["confidence_quality"],
        "uncalibrated_prior",
        "calibrated confidence fallback",
    )
    assert_equal(
        result["utility_estimate"]["utility_decision"] in {"trade_candidate", "do_not_trade"},
        True,
        "utility estimate is observe-only",
    )


def test_sell_signals_pass_through_without_order_authority():
    result = decision_policy.evaluate_decision_policy("AAPL", "sell")

    assert_equal(result["decision"], "allow", "sell decision")
    assert_equal(result["size_multiplier"], 1.0, "sell size multiplier")
    assert_equal(result.get("can_submit_orders"), False, "can submit orders")
    assert_equal(
        result["utility_estimate"]["utility_decision"],
        "not_applicable",
        "sell utility estimate",
    )


def test_portfolio_duplicate_risk_can_size_down_policy():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "TSM",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 90, "decision": "allow"},
            },
            account_state={
                "balance": 100_000,
                "proposed_position_size_pct": 1.0,
                "open_positions": [
                    {"symbol": "NVDA", "qty": 10, "market_value": 6_000},
                    {"symbol": "AMD", "qty": 20, "market_value": 5_000},
                ],
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "size_down", "decision")
    assert_lte(result["size_multiplier"], 0.75, "size multiplier")
    assert_equal(
        result["portfolio_decision"]["decision"],
        "size_down",
        "portfolio decision",
    )


def test_execution_quality_can_size_down_policy():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 90, "decision": "allow"},
            },
            account_state={
                "execution_quality": {
                    "decision": "size_down",
                    "size_multiplier": 0.50,
                    "net_execution_cost_pct": 0.55,
                    "fill_quality": "degraded",
                },
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "size_down", "decision")
    assert_lte(result["size_multiplier"], 0.50, "size multiplier")
    assert_equal(
        result["execution_quality"]["decision"],
        "size_down",
        "execution quality",
    )


def test_duplicate_portfolio_risk_blocks_even_with_strong_standalone_chart():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "TSM",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 95, "decision": "allow"},
                "prediction": {"prediction_decision": "allow", "prediction_score": 80},
            },
            account_state={
                "setup_quality": {"score": 92, "recommendation": "buy"},
                "portfolio_decision": {
                    "decision": "block",
                    "size_multiplier": 0.0,
                    "duplicate_risk_score": 0.94,
                    "crowded_theme": "semiconductors",
                },
                "execution_quality": {"decision": "allow"},
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "block", "portfolio block wins")
    assert_equal(result["size_multiplier"], 0.0, "size")
    assert_true("portfolio duplicate risk says block" in result["risks"], "risk reason")


def test_utility_estimate_cannot_block_or_size_by_itself():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 90, "decision": "allow"},
                "prediction": {"prediction_decision": "allow", "prediction_score": 80},
            },
            account_state={
                "utility_estimate": {
                    "utility_decision": "do_not_trade",
                    "portfolio_adjusted_utility_pct": -9.0,
                    "utility_scope": "telemetry_observe_only",
                },
                "portfolio_decision": {"decision": "allow"},
                "execution_quality": {"decision": "allow"},
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "allow", "utility telemetry is not authority")
    assert_equal(result["size_multiplier"], 1.0, "utility telemetry does not size")


def test_calibrated_confidence_cannot_change_live_authority_by_itself():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 90, "decision": "allow"},
                "prediction": {"prediction_decision": "allow", "prediction_score": 80},
            },
            account_state={
                "calibrated_confidence": {
                    "primary_realized_win_rate": 0.05,
                    "primary_sample_size": 500,
                    "confidence_quality": "medium",
                },
                "portfolio_decision": {"decision": "allow"},
                "execution_quality": {"decision": "allow"},
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "allow", "calibration telemetry is not authority")
    assert_equal(result["size_multiplier"], 1.0, "calibration does not size")


def test_canonical_snapshot_payload_cannot_change_decision_by_itself():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 90, "decision": "allow"},
            },
            account_state={
                "canonical_intelligence_json": '{"advisory_authority_state":{"utility_estimate":{"utility_decision":"do_not_trade"}}}',
                "portfolio_decision": {"decision": "allow"},
                "execution_quality": {"decision": "allow"},
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "allow", "canonical persistence is inert")


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
    test_portfolio_duplicate_risk_can_size_down_policy()
    print("[OK] test_portfolio_duplicate_risk_can_size_down_policy")
    test_execution_quality_can_size_down_policy()
    print("[OK] test_execution_quality_can_size_down_policy")
    test_duplicate_portfolio_risk_blocks_even_with_strong_standalone_chart()
    print("[OK] test_duplicate_portfolio_risk_blocks_even_with_strong_standalone_chart")
    test_utility_estimate_cannot_block_or_size_by_itself()
    print("[OK] test_utility_estimate_cannot_block_or_size_by_itself")
    test_calibrated_confidence_cannot_change_live_authority_by_itself()
    print("[OK] test_calibrated_confidence_cannot_change_live_authority_by_itself")
    test_canonical_snapshot_payload_cannot_change_decision_by_itself()
    print("[OK] test_canonical_snapshot_payload_cannot_change_decision_by_itself")
    test_decision_policy_module_does_not_import_order_execution()
    print("[OK] test_decision_policy_module_does_not_import_order_execution")
    print("\nAll 10 decision policy tests passed.")
