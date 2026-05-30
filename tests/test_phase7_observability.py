#!/usr/bin/env python3
"""Phase 7 observability and policy-control tests."""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.observability import metrics_snapshot, reset_metrics
from services.policies import entry_policy, execution_policy, sizing_policy
from services.policy_controls import policy_family_enabled


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy")


def test_policy_family_kill_switch_from_env():
    previous = os.environ.get("POLICY_ENTRY_ENABLED")
    os.environ["POLICY_ENTRY_ENABLED"] = "false"
    try:
        assert_equal(policy_family_enabled("entry"), False, "entry policy disabled")
        gate = entry_policy.evaluate_signal_quality_gate(
            trend_direction="bearish",
            trend_strength="weak",
            market_bias="avoid",
            setup_label="avoid_stretched_above_vwap_strength",
            setup_policy_action="block",
            momentum_direction="falling",
            momentum_pct=-1.0,
            consecutive_buy_count=0,
        )
        assert_equal(gate["prediction_decision"], "pass", "disabled entry policy fails open")
        assert_equal(gate["policy_family_enabled"], False, "gate exposes disabled state")
    finally:
        if previous is None:
            os.environ.pop("POLICY_ENTRY_ENABLED", None)
        else:
            os.environ["POLICY_ENTRY_ENABLED"] = previous


def test_sizing_kill_switch_returns_uncapped_adjusted_size():
    previous = os.environ.get("POLICY_SIZING_ENABLED")
    os.environ["POLICY_SIZING_ENABLED"] = "false"
    try:
        account_state = {"buy_opportunity": {"buy_opportunity_recommendation": "avoid"}}
        final_pct = sizing_policy.apply_buy_opportunity_sizing(
            symbol="AAPL",
            action="buy",
            base_position_size_pct=1.0,
            risk_multiplier=1.25,
            account_state=account_state,
        )
        assert_equal(final_pct, 1.25, "disabled sizing returns adjusted base size")
        assert_equal(account_state["buy_opportunity_sizing"]["enabled"], False, "disabled sizing noted")
    finally:
        if previous is None:
            os.environ.pop("POLICY_SIZING_ENABLED", None)
        else:
            os.environ["POLICY_SIZING_ENABLED"] = previous


def test_execution_kill_switch_skips_rotation_and_fails_open_second_look():
    previous = os.environ.get("POLICY_EXECUTION_ENABLED")
    os.environ["POLICY_EXECUTION_ENABLED"] = "false"
    try:
        ok, reason = execution_policy.pre_order_safety_check(
            symbol="AAPL",
            action="buy",
            signal_price=100,
            account_state={},
            market_data_service=None,
            broker_service=None,
            validate_spread_with_retry=lambda *args, **kwargs: {"ok": True},
            symbol_max_spread_pct={},
            max_bid_ask_spread_pct=1.0,
            max_signal_price_drift_pct=1.0,
            logger=None,
        )
        assert_equal(ok, True, "disabled execution safety check fails open")
        assert_equal(reason, "execution_policy_disabled", "disabled execution reason")

        rotated, reason, detail = execution_policy.try_portfolio_rotation(
            candidate_symbol="AAPL",
            candidate_price=100.0,
            account_state={},
            now_dt=None,
            enabled=True,
            max_per_day=1,
            min_candidate_score=1,
            rotation_count_today=lambda: 0,
            rotation_candidate_score=lambda *_: (99, "test"),
            weakest_rotation_holding=lambda _: {"symbol": "MSFT"},
            place_order=lambda **_: {"order_id": "1"},
            log_trade=lambda *_, **__: None,
            last_order={},
            write_cooldown=lambda *_, **__: None,
            last_sell={},
            write_recent_sell=lambda *_, **__: None,
            logger=None,
        )
        assert_equal(rotated, False, "disabled execution skips rotation")
        assert_equal(reason, "execution_policy_disabled", "disabled rotation reason")
        assert_equal(detail, {}, "disabled rotation detail")
    finally:
        if previous is None:
            os.environ.pop("POLICY_EXECUTION_ENABLED", None)
        else:
            os.environ["POLICY_EXECUTION_ENABLED"] = previous


def test_policy_comparison_metrics_record_agreement_rates():
    reset_metrics()
    entry_policy.evaluate_signal_quality_gate(
        trend_direction="bullish",
        trend_strength="confirmed",
        market_bias="buy",
        setup_label="confirmed_near_vwap_recovery",
        setup_policy_action="boost",
        momentum_direction="rising",
        momentum_pct=0.5,
        consecutive_buy_count=3,
        ml_prediction={"prediction_score": 20},
    )
    snapshot = metrics_snapshot()
    item = snapshot["policy_disagreement_rates"]["deterministic_signal_quality_vs_ml_prediction"]
    assert_equal(item["comparisons"], 1, "comparison count")
    assert_equal(item["disagreements"], 1, "disagreement count")
    assert_true(item["disagreement_rate"] > 0, "disagreement rate")


def main():
    tests = [
        test_policy_family_kill_switch_from_env,
        test_sizing_kill_switch_returns_uncapped_adjusted_size,
        test_execution_kill_switch_skips_rotation_and_fails_open_second_look,
        test_policy_comparison_metrics_record_agreement_rates,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} Phase 7 observability tests passed.")


if __name__ == "__main__":
    main()
