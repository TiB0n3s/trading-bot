#!/usr/bin/env python3
"""Tests for canonical signal safety gates."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.decision.gates.signal_safety import (  # noqa: E402
    evaluate_cash_safe_gate,
    evaluate_stale_signal_gate,
    evaluate_symbol_override_gate,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_stale_signal_gate_blocks_with_trace_outputs():
    gate = evaluate_stale_signal_gate(
        raw_signal={"symbol": "AAPL"},
        parse_stale_signal=lambda _: (True, 122.0, "signal too old"),
    )

    assert_equal(gate.gate_id, "stale_signal", "gate id")
    assert_equal(gate.decision, "block", "decision")
    assert_equal(gate.enforced, True, "enforced")
    assert_equal(gate.outputs["rejection_category"], "stale_signal", "category")
    assert_equal(gate.outputs["metadata"]["age_seconds"], 122.0, "age")


def test_fresh_signal_gate_outputs_account_state_update():
    gate = evaluate_stale_signal_gate(
        raw_signal={"symbol": "AAPL"},
        parse_stale_signal=lambda _: (False, 3.14159, "fresh"),
    )

    assert_equal(gate.decision, "pass", "decision")
    assert_equal(
        gate.outputs["account_state_updates"],
        {"signal_age_seconds": 3.14},
        "updates",
    )


def test_cash_safe_gate_blocks_unapproved_symbol():
    gate = evaluate_cash_safe_gate(
        symbol="TSLA",
        action="buy",
        account_state={"open_position_count": 0},
        cash_safe_mode=True,
        cash_safe_symbols={"AAPL"},
        max_open_positions=2,
        max_new_buys_per_symbol_per_day=1,
        cash_safe_buys_today=lambda _: 0,
    )

    assert_equal(gate.decision, "block", "decision")
    assert_equal(gate.outputs["rejection_category"], "cash_safe_symbol", "category")


def test_cash_safe_gate_blocks_daily_symbol_limit():
    gate = evaluate_cash_safe_gate(
        symbol="AAPL",
        action="buy",
        account_state={"open_position_count": 0},
        cash_safe_mode=True,
        cash_safe_symbols={"AAPL"},
        max_open_positions=2,
        max_new_buys_per_symbol_per_day=1,
        cash_safe_buys_today=lambda _: 1,
    )

    assert_equal(gate.decision, "block", "decision")
    assert_equal(
        gate.outputs["rejection_category"],
        "cash_safe_daily_symbol_limit",
        "category",
    )


def test_symbol_override_gate_blocks_with_reason_metadata():
    gate = evaluate_symbol_override_gate(
        symbol="AAPL",
        action="buy",
        symbol_override_block=lambda symbol, action: f"{symbol} {action} blocked",
    )

    assert_equal(gate.decision, "block", "decision")
    assert_equal(gate.outputs["rejection_category"], "symbol_override", "category")
    assert_equal(
        gate.outputs["metadata"],
        {"override_reason": "AAPL buy blocked"},
        "metadata",
    )


def main():
    tests = [
        test_stale_signal_gate_blocks_with_trace_outputs,
        test_fresh_signal_gate_outputs_account_state_update,
        test_cash_safe_gate_blocks_unapproved_symbol,
        test_cash_safe_gate_blocks_daily_symbol_limit,
        test_symbol_override_gate_blocks_with_reason_metadata,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} signal safety gate tests passed.")


if __name__ == "__main__":
    main()
