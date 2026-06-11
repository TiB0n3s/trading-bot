#!/usr/bin/env python3
"""Unit tests for the extracted execution boundary."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.execution_service import execute_approved_order, execute_order  # noqa: E402


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_second_look_rejection_is_normalized():
    outcome = execute_order(
        symbol="AAPL",
        action="buy",
        signal={"symbol": "AAPL", "action": "buy"},
        signal_price=100.0,
        decision={"position_size_pct": 0.5},
        account_state={},
        position_size_pct=0.5,
        execution_mode="paper",
        pre_order_safety_check=lambda **_: (False, "spread too wide"),
        one_bar_confirmation_hold=lambda **_: (True, "ok"),
        make_client_order_id=lambda *_: "cid",
        place_order=lambda **_: {"order_id": "should_not_submit"},
        log=logging.getLogger("test_execution_service"),
    )
    assert_equal(outcome.status, "rejected", "status")
    assert_equal(outcome.rejection_category, "second_look", "category")
    assert_equal(outcome.submitted, False, "submitted")


def test_one_bar_rejection_updates_account_state():
    outcome = execute_order(
        symbol="AAPL",
        action="buy",
        signal={"symbol": "AAPL", "action": "buy"},
        signal_price=100.0,
        decision={"position_size_pct": 0.5},
        account_state={},
        position_size_pct=0.5,
        execution_mode="paper",
        pre_order_safety_check=lambda **_: (True, "ok"),
        one_bar_confirmation_hold=lambda **_: (False, "confirmation failed"),
        make_client_order_id=lambda *_: "cid",
        place_order=lambda **_: {"order_id": "should_not_submit"},
        log=logging.getLogger("test_execution_service"),
    )
    assert_equal(outcome.rejection_category, "one_bar_confirmation_hold", "category")
    assert_equal(
        outcome.account_state_updates["one_bar_confirmation_hold"]["allowed"],
        False,
        "one bar allowed",
    )


def test_null_order_flips_decision_to_failed_submission():
    outcome = execute_order(
        symbol="AAPL",
        action="buy",
        signal={"symbol": "AAPL", "action": "buy"},
        signal_price=100.0,
        decision={"position_size_pct": 0.5},
        account_state={},
        position_size_pct=0.5,
        execution_mode="paper",
        pre_order_safety_check=lambda **_: (True, "ok"),
        one_bar_confirmation_hold=lambda **_: (True, "ok"),
        make_client_order_id=lambda *_: "cid",
        place_order=lambda **_: None,
        log=logging.getLogger("test_execution_service"),
    )
    assert_equal(outcome.status, "submit_failed", "status")
    assert_equal(outcome.decision_updates["approved"], False, "approved update")
    assert_equal(outcome.failure_reason, "broker returned no order_result", "failure")


def test_dry_run_returns_order_without_submit():
    outcome = execute_order(
        symbol="AAPL",
        action="sell",
        signal={"symbol": "AAPL", "action": "sell"},
        signal_price=100.0,
        decision={"position_size_pct": 1.0},
        account_state={},
        position_size_pct=1.0,
        execution_mode="dry_run",
        pre_order_safety_check=lambda **_: (_ for _ in ()).throw(AssertionError("unused")),
        one_bar_confirmation_hold=lambda **_: (_ for _ in ()).throw(AssertionError("unused")),
        make_client_order_id=lambda *_: "cid",
        place_order=lambda **_: {"order_id": "unused"},
        log=logging.getLogger("test_execution_service"),
    )
    assert_equal(outcome.status, "dry_run", "status")
    assert_equal(outcome.order_result["status"], "dry_run", "order status")
    assert_equal(outcome.submitted, False, "submitted")


def test_live_circuit_breaker_blocks_buy_before_second_look():
    outcome = execute_order(
        symbol="AAPL",
        action="buy",
        signal={"symbol": "AAPL", "action": "buy"},
        signal_price=100.0,
        decision={"position_size_pct": 0.5},
        account_state={"max_drawdown_pct": 3.5},
        position_size_pct=0.5,
        execution_mode="paper",
        pre_order_safety_check=lambda **_: (_ for _ in ()).throw(AssertionError("unused")),
        one_bar_confirmation_hold=lambda **_: (_ for _ in ()).throw(AssertionError("unused")),
        make_client_order_id=lambda *_: "cid",
        place_order=lambda **_: {"order_id": "should_not_submit"},
        log=logging.getLogger("test_execution_service"),
    )

    assert_equal(outcome.status, "rejected", "status")
    assert_equal(outcome.rejection_category, "live_circuit_breaker", "category")
    assert_equal(outcome.submitted, False, "submitted")


def test_execution_quality_block_blocks_buy_before_order_routing():
    outcome = execute_order(
        symbol="AAPL",
        action="buy",
        signal={"symbol": "AAPL", "action": "buy"},
        signal_price=100.0,
        decision={"position_size_pct": 0.5},
        account_state={"execution_quality": {"decision": "block", "reason": "spread too wide"}},
        position_size_pct=0.5,
        execution_mode="paper",
        pre_order_safety_check=lambda **_: (_ for _ in ()).throw(AssertionError("unused")),
        one_bar_confirmation_hold=lambda **_: (_ for _ in ()).throw(AssertionError("unused")),
        make_client_order_id=lambda *_: "cid",
        place_order=lambda **_: {"order_id": "should_not_submit"},
        log=logging.getLogger("test_execution_service"),
    )

    assert_equal(outcome.status, "rejected", "status")
    assert_equal(outcome.rejection_category, "execution_quality", "category")
    assert_equal(outcome.rejection_reason, "spread too wide", "reason")
    assert_equal(outcome.submitted, False, "submitted")


def test_live_execution_quality_computes_toxic_vpin_block_before_order_routing():
    outcome = execute_order(
        symbol="AAPL",
        action="buy",
        signal={"symbol": "AAPL", "action": "buy"},
        signal_price=100.0,
        decision={"position_size_pct": 0.5},
        account_state={
            "signal_price": 100.0,
            "bar_pattern_features": {"vpin_toxicity_20": 0.94},
            "quote_snapshot": {"bid": 99.99, "ask": 100.01},
        },
        position_size_pct=0.5,
        execution_mode="paper",
        pre_order_safety_check=lambda **_: (_ for _ in ()).throw(AssertionError("unused")),
        one_bar_confirmation_hold=lambda **_: (_ for _ in ()).throw(AssertionError("unused")),
        make_client_order_id=lambda *_: "cid",
        place_order=lambda **_: {"order_id": "should_not_submit"},
        log=logging.getLogger("test_execution_service"),
    )

    assert_equal(outcome.status, "rejected", "status")
    assert_equal(outcome.rejection_category, "execution_quality", "category")
    assert "toxic_vpin" in outcome.rejection_reason
    assert_equal(outcome.submitted, False, "submitted")


def test_zero_final_buy_size_blocks_before_order_routing():
    calls = {"execute": 0, "log_trade": 0}

    class _RejectAdapter:
        def reject_approval_decision(self, *_args, **_kwargs):
            raise AssertionError("rejection adapter should not be needed")

    decision = {"approved": True, "position_size_pct": 1.0}
    account_state = {"slippage_kelly_sizing": {"reason": "friction_ratio_exceeds_0.20"}}

    outcome = execute_approved_order(
        signal={"symbol": "AAPL", "action": "buy"},
        symbol="AAPL",
        action="buy",
        price=100.0,
        account_state=account_state,
        dedupe_key=None,
        current_et=None,
        decision=decision,
        execution_mode="paper",
        apply_final_sizing=lambda **_: type(
            "SizingDecision",
            (),
            {
                "requested_size_pct": 1.0,
                "final_size_pct": 0.0,
                "dominant_limiter": "slippage_kelly",
                "active_caps": [],
                "conviction_stack": {},
            },
        )(),
        apply_buy_opportunity_sizing=lambda **kwargs: kwargs["base_position_size_pct"],
        execute_order_func=lambda **_: calls.__setitem__("execute", calls["execute"] + 1),
        pre_order_safety_check=lambda **_: (True, "ok"),
        one_bar_confirmation_hold=lambda **_: (True, "ok"),
        make_client_order_id=lambda *_: "cid",
        place_order=lambda **_: {"order_id": "should_not_submit"},
        execution_rejection_decision=lambda execution: execution,
        deterministic_rejection=lambda **kwargs: kwargs,
        rejection_adapter=_RejectAdapter(),
        log_trade=lambda *_args, **_kwargs: calls.__setitem__("log_trade", calls["log_trade"] + 1),
        record_webhook_status=lambda **_: None,
        write_cooldown=lambda *_: None,
        write_recent_sell=lambda *_: None,
        last_order={},
        last_sell={},
        log=logging.getLogger("test_execution_service"),
    )

    assert_equal(outcome.status, "not_submitted", "status")
    assert_equal(outcome.submitted, False, "submitted")
    assert_equal(outcome.rejection_category, "slippage_kelly", "category")
    assert_equal(calls["execute"], 0, "execute calls")
    assert_equal(calls["log_trade"], 1, "log trade calls")
    assert_equal(decision["approved"], False, "approved")
    assert_equal(account_state["order_path_blocked"], "slippage_kelly", "block source")


def main():
    tests = [
        test_second_look_rejection_is_normalized,
        test_one_bar_rejection_updates_account_state,
        test_null_order_flips_decision_to_failed_submission,
        test_dry_run_returns_order_without_submit,
        test_live_circuit_breaker_blocks_buy_before_second_look,
        test_execution_quality_block_blocks_buy_before_order_routing,
        test_live_execution_quality_computes_toxic_vpin_block_before_order_routing,
        test_zero_final_buy_size_blocks_before_order_routing,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} execution service tests passed.")


if __name__ == "__main__":
    main()
