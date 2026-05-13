"""
Focused tests for fast-lane sell-flip gating.

Run:
  python3 tests/test_fast_lane_sell.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import _compute_trend
from indicator_state import is_fast_lane_sell_flip


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_fast_lane_allows_two_bar_sell_flip_when_required_is_two():
    trend = _compute_trend(["sell", "sell", "buy", "buy"])
    assert_equal(is_fast_lane_sell_flip(trend, 2), True, "fast lane should allow clean 2-bar sell flip")


def test_fast_lane_blocks_when_required_is_three():
    trend = _compute_trend(["sell", "sell", "buy", "buy"])
    assert_equal(is_fast_lane_sell_flip(trend, 3), False, "fast lane should not allow when required is 3")


def test_fast_lane_blocks_non_flip_bearish_state():
    trend = _compute_trend(["sell", "sell"])
    assert_equal(is_fast_lane_sell_flip(trend, 2), False, "fast lane should require an actual sell_flip")


def test_fast_lane_blocks_bullish_state():
    trend = _compute_trend(["buy", "buy", "sell", "sell"])
    assert_equal(is_fast_lane_sell_flip(trend, 2), False, "fast lane should block bullish state")


def main():
    tests = [
        test_fast_lane_allows_two_bar_sell_flip_when_required_is_two,
        test_fast_lane_blocks_when_required_is_three,
        test_fast_lane_blocks_non_flip_bearish_state,
        test_fast_lane_blocks_bullish_state,
    ]

    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print()
    print(f"All {len(tests)} fast-lane sell tests passed.")


if __name__ == "__main__":
    main()