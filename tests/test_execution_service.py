#!/usr/bin/env python3
"""Unit tests for the extracted execution boundary."""

from __future__ import annotations

import logging
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.execution_service import execute_order


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


def main():
    tests = [
        test_second_look_rejection_is_normalized,
        test_one_bar_rejection_updates_account_state,
        test_null_order_flips_decision_to_failed_submission,
        test_dry_run_returns_order_without_submit,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} execution service tests passed.")


if __name__ == "__main__":
    main()
