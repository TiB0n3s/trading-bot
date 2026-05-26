"""
Focused tests for setup policy labels.

Run:
  python3 tests/test_setup_policy.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from setup_policy import evaluate_setup_policy


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_above_vwap_strength_continuation_is_watch_not_boost():
    result = evaluate_setup_policy("above_vwap_strength_continuation")

    assert_equal(result["setup_policy_action"], "allow", "policy action")
    assert_equal(result["setup_confidence_adjustment"], 0, "confidence adjustment")


def test_confirmed_near_vwap_recovery_still_boosts():
    result = evaluate_setup_policy("confirmed_near_vwap_recovery")

    assert_equal(result["setup_policy_action"], "boost", "policy action")


def main():
    tests = [
        test_above_vwap_strength_continuation_is_watch_not_boost,
        test_confirmed_near_vwap_recovery_still_boosts,
    ]

    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print()
    print(f"All {len(tests)} setup-policy tests passed.")


if __name__ == "__main__":
    main()
