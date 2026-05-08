#!/usr/bin/env python3
"""
Targeted tests for trend computation.

Run:
  python3 tests/test_trend.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app import _compute_trend


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_empty_history():
    t = _compute_trend([])
    assert_equal(t["direction"], "neutral", "empty direction")
    assert_equal(t["strength"], "weak", "empty strength")
    assert_equal(t["consecutive_count"], 0, "empty count")


def test_single_buy_is_neutral_weak():
    t = _compute_trend(["buy"])
    assert_equal(t["direction"], "neutral", "single buy direction")
    assert_equal(t["strength"], "weak", "single buy strength")
    assert_equal(t["consecutive_count"], 1, "single buy count")


def test_two_buys_is_neutral_weak():
    t = _compute_trend(["buy", "buy"])
    assert_equal(t["direction"], "neutral", "two buys direction")
    assert_equal(t["strength"], "weak", "two buys strength")
    assert_equal(t["consecutive_count"], 2, "two buys count")


def test_three_buys_is_bullish_developing():
    t = _compute_trend(["buy", "buy", "buy"])
    assert_equal(t["direction"], "bullish", "three buys direction")
    assert_equal(t["strength"], "developing", "three buys strength")
    assert_equal(t["consecutive_count"], 3, "three buys count")


def test_five_buys_is_bullish_confirmed():
    t = _compute_trend(["buy", "buy", "buy", "buy", "buy"])
    assert_equal(t["direction"], "bullish", "five buys direction")
    assert_equal(t["strength"], "confirmed", "five buys strength")
    assert_equal(t["consecutive_count"], 5, "five buys count")


def test_sell_resets_buy_streak():
    t = _compute_trend(["sell", "buy", "buy", "buy"])
    assert_equal(t["direction"], "neutral", "sell reset direction")
    assert_equal(t["strength"], "weak", "sell reset strength")
    assert_equal(t["consecutive_count"], 1, "sell reset count")
    assert_equal(t["last_signal"], "sell", "sell reset last_signal")


def test_three_sells_is_bearish_developing():
    t = _compute_trend(["sell", "sell", "sell"])
    assert_equal(t["direction"], "bearish", "three sells direction")
    assert_equal(t["strength"], "developing", "three sells strength")
    assert_equal(t["consecutive_count"], 3, "three sells count")


def main():
    tests = [
        test_empty_history,
        test_single_buy_is_neutral_weak,
        test_two_buys_is_neutral_weak,
        test_three_buys_is_bullish_developing,
        test_five_buys_is_bullish_confirmed,
        test_sell_resets_buy_streak,
        test_three_sells_is_bearish_developing,
    ]

    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print()
    print(f"All {len(tests)} trend tests passed.")


if __name__ == "__main__":
    main()
