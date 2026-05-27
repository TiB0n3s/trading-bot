"""
Focused tests for position-manager exit guards.

Run:
  python3 tests/test_position_manager.py
"""

import sys
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

os.environ.setdefault("ALPACA_API_KEY", "test-key")
os.environ.setdefault("ALPACA_SECRET_KEY", "test-secret")

from position_manager import continuation_exit_delay_reason
from position_manager import normalize_exit_for_share_qty
from position_manager import planned_partial_sell_qty


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy value, got {value!r}")


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_continuation_delays_soft_full_exit_when_tape_supports():
    reason = continuation_exit_delay_reason(
        current_pl_pct=-0.20,
        momentum_15m=0.12,
        momentum_30m=0.08,
        vwap_dist_pct=0.03,
    )

    assert_true(reason, "delay reason")
    assert_true("full exit delayed" in reason, "reason text")


def test_continuation_does_not_delay_hard_loss():
    reason = continuation_exit_delay_reason(
        current_pl_pct=-0.90,
        momentum_15m=0.12,
        momentum_30m=0.08,
        vwap_dist_pct=0.10,
    )

    assert_equal(reason, None, "hard loss delay")


def test_partial_exit_promotes_to_full_when_position_is_one_share():
    reasons = ["profit giveback trigger"]

    action, sell_fraction, severity = normalize_exit_for_share_qty(
        action="sell_partial",
        sell_fraction=0.50,
        qty=1,
        severity="medium",
        reasons=reasons,
    )

    assert_equal(action, "sell_full", "action")
    assert_equal(sell_fraction, 1.0, "sell fraction")
    assert_equal(severity, "high", "severity")
    assert_true("partial_exit_promoted_to_full" in reasons[-1], "promotion reason")


def test_partial_exit_remains_partial_when_share_qty_is_actionable():
    reasons = ["profit giveback trigger"]

    action, sell_fraction, severity = normalize_exit_for_share_qty(
        action="sell_partial",
        sell_fraction=0.50,
        qty=8,
        severity="medium",
        reasons=reasons,
    )

    assert_equal(action, "sell_partial", "action")
    assert_equal(sell_fraction, 0.50, "sell fraction")
    assert_equal(severity, "medium", "severity")
    assert_equal(planned_partial_sell_qty(8, 0.50), 4, "planned qty")


def main():
    tests = [
        test_continuation_delays_soft_full_exit_when_tape_supports,
        test_continuation_does_not_delay_hard_loss,
        test_partial_exit_promotes_to_full_when_position_is_one_share,
        test_partial_exit_remains_partial_when_share_qty_is_actionable,
    ]

    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print()
    print(f"All {len(tests)} position-manager tests passed.")


if __name__ == "__main__":
    main()
