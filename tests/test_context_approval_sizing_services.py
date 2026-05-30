#!/usr/bin/env python3
"""Unit tests for extracted context, approval, and sizing services."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.approval_service import evaluate_approval_decision
from services.context_builder import build_final_signal_context
from services.sizing_service import apply_final_sizing, apply_size_cap, build_conviction_stack


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_context_builder_sanitizes_claude_context():
    account_state = {
        "adaptive_buy_confirmation": {"required_buy_confirmations": 3, "reasons": ["test"]},
        "market_alignment": {"aligned_for_buy": True, "reason": "aligned"},
        "setup_observation": {"setup_label": "clean"},
    }
    built = build_final_signal_context(account_state=account_state, trend_table={"AAPL": {}})
    assert_equal("adaptive_buy_confirmation" in built.claude_account_state, False, "adaptive stripped")
    assert_equal("market_alignment" in built.claude_account_state, False, "alignment stripped")
    assert_equal(
        built.claude_account_state["market_context_summary"]["required_confirmations"],
        3,
        "summary confirmations",
    )


def test_approval_service_converts_low_confidence_to_category():
    result = evaluate_approval_decision(
        signal={"symbol": "AAPL", "action": "buy"},
        action="buy",
        claude_account_state={},
        evaluate_signal=lambda *_: {
            "approved": True,
            "confidence": "low",
            "reason": "too weak",
        },
        cash_safe_mode=False,
        market_bias={},
        account_state={},
        medium_confidence_override=lambda **_: (False, "no override"),
        tape_exception_enabled=False,
    )
    assert_equal(result.approved, False, "approved")
    assert_equal(result.category, "confidence_gate", "category")


def test_sizing_service_preserves_legacy_sell_default_size():
    decision = {"position_size_pct": 0}
    sizing = apply_final_sizing(
        symbol="AAPL",
        action="sell",
        decision=decision,
        risk_multiplier=1.0,
        account_state={},
        apply_buy_opportunity_sizing=lambda **kwargs: kwargs["base_position_size_pct"]
        * kwargs["risk_multiplier"],
    )
    assert_equal(sizing.final_size_pct, 1.0, "sell default size")


def test_apply_size_cap_keeps_tightest_cap():
    state = {"max_position_size_pct_override": 0.75}
    applied = apply_size_cap(
        state,
        cap_pct=0.5,
        state_key="weak_prediction_setup_gate",
        payload={"triggered": True},
    )
    assert_equal(applied, 0.5, "applied cap")
    assert_equal(state["weak_prediction_setup_gate"]["triggered"], True, "payload")


def test_conviction_stack_sets_dominant_limiter():
    account_state = {
        "weak_prediction_setup_gate": {"triggered": True},
        "buy_opportunity": {"buy_opportunity_recommendation": "watch"},
        "strategy_observation": {"trader_brain": {"score": 30}},
    }
    stack = build_conviction_stack(
        action="buy",
        account_state=account_state,
        ml_prediction_bucket=lambda raw: "weak_below_45",
        compute_dominant_limiter=lambda state: "weak_prediction_degraded",
    )
    assert_equal(stack["buy_opportunity"], "watch", "buy opportunity")
    assert_equal(account_state["dominant_limiter"], "weak_prediction_degraded", "limiter")


def main():
    tests = [
        test_context_builder_sanitizes_claude_context,
        test_approval_service_converts_low_confidence_to_category,
        test_sizing_service_preserves_legacy_sell_default_size,
        test_apply_size_cap_keeps_tightest_cap,
        test_conviction_stack_sets_dominant_limiter,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} context/approval/sizing service tests passed.")


if __name__ == "__main__":
    main()
