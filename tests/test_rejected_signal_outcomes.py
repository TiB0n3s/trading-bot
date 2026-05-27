"""
Focused tests for rejected-signal counterfactual outcome math.

Run:
  python3 tests/test_rejected_signal_outcomes.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from rejected_signal_outcome_builder import compute_outcome


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_close(actual, expected, label, ndigits=6):
    if round(float(actual), ndigits) != round(float(expected), ndigits):
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def sample_bars():
    return [
        {"timestamp": "2026-05-26T09:35:00-04:00", "close": 100.0, "high": 100.2, "low": 99.8},
        {"timestamp": "2026-05-26T09:40:00-04:00", "close": 101.0, "high": 101.2, "low": 100.5},
        {"timestamp": "2026-05-26T09:50:00-04:00", "close": 102.0, "high": 102.4, "low": 100.8},
        {"timestamp": "2026-05-26T10:05:00-04:00", "close": 99.0, "high": 102.6, "low": 98.6},
        {"timestamp": "2026-05-26T10:35:00-04:00", "close": 103.0, "high": 103.5, "low": 98.5},
        {"timestamp": "2026-05-26T16:00:00-04:00", "close": 104.0, "high": 104.2, "low": 103.7},
    ]


def test_buy_outcome_uses_raw_forward_returns():
    outcome = compute_outcome(
        {
            "timestamp": "2026-05-26T08:35:00-05:00",
            "action": "buy",
            "signal_price": 100.0,
        },
        sample_bars(),
    )

    assert_close(outcome["return_5m"], 1.0, "5m return")
    assert_close(outcome["return_15m"], 2.0, "15m return")
    assert_close(outcome["return_30m"], -1.0, "30m return")
    assert_close(outcome["return_60m"], 3.0, "60m return")
    assert_close(outcome["return_eod"], 4.0, "eod return")
    assert_close(outcome["max_favorable_60m"], 3.5, "mfe")
    assert_close(outcome["max_adverse_60m"], -1.5, "mae")
    assert_equal(outcome["label_status"], "labeled", "status")


def test_sell_outcome_is_action_adjusted():
    outcome = compute_outcome(
        {
            "timestamp": "2026-05-26T08:35:00-05:00",
            "action": "sell",
            "signal_price": 100.0,
        },
        sample_bars(),
    )

    assert_close(outcome["return_5m"], -1.0, "5m return")
    assert_close(outcome["return_30m"], 1.0, "30m return")
    assert_close(outcome["max_favorable_60m"], 1.5, "sell mfe")
    assert_close(outcome["max_adverse_60m"], -3.5, "sell mae")


def test_near_close_partial_reason():
    outcome = compute_outcome(
        {
            "timestamp": "2026-05-26T15:40:00-04:00",
            "action": "buy",
            "signal_price": 100.0,
        },
        [
            {"timestamp": "2026-05-26T15:45:00-04:00", "close": 100.2, "high": 100.3, "low": 99.9},
            {"timestamp": "2026-05-26T16:00:00-04:00", "close": 100.5, "high": 100.6, "low": 100.1},
        ],
    )

    assert_equal(outcome["label_status"], "partial", "status")
    assert_equal(outcome["partial_reason"], "near_close_no_60m_window", "partial reason")
    assert_equal(outcome["return_60m"], None, "near-close 60m")


def test_missing_forward_bars_partial_reason():
    outcome = compute_outcome(
        {
            "timestamp": "2026-05-26T09:35:00-04:00",
            "action": "buy",
            "signal_price": 100.0,
        },
        [
            {"timestamp": "2026-05-26T09:40:00-04:00", "close": 101.0, "high": 101.2, "low": 99.9},
            {"timestamp": "2026-05-26T09:50:00-04:00", "close": 102.0, "high": 102.3, "low": 100.5},
        ],
    )

    assert_equal(outcome["label_status"], "partial", "status")
    assert_equal(outcome["partial_reason"], "missing_forward_bars", "partial reason")
    assert_close(outcome["return_5m"], 1.0, "5m return")
    assert_close(outcome["return_15m"], 2.0, "15m return")
    assert_equal(outcome["return_30m"], None, "30m return")


def test_excursions_are_action_adjusted_and_sign_bounded():
    buy_outcome = compute_outcome(
        {
            "timestamp": "2026-05-26T08:35:00-05:00",
            "action": "buy",
            "signal_price": 100.0,
        },
        [
            {"timestamp": "2026-05-26T09:40:00-04:00", "close": 99.0, "high": 99.5, "low": 98.0},
            {"timestamp": "2026-05-26T10:35:00-04:00", "close": 98.5, "high": 99.4, "low": 97.0},
        ],
    )
    sell_outcome = compute_outcome(
        {
            "timestamp": "2026-05-26T08:35:00-05:00",
            "action": "sell",
            "signal_price": 100.0,
        },
        [
            {"timestamp": "2026-05-26T09:40:00-04:00", "close": 101.0, "high": 102.0, "low": 100.5},
            {"timestamp": "2026-05-26T10:35:00-04:00", "close": 101.5, "high": 103.0, "low": 100.6},
        ],
    )

    assert_equal(buy_outcome["max_favorable_60m"], 0.0, "buy no-favorable mfe")
    assert_close(buy_outcome["max_adverse_60m"], -3.0, "buy adverse")
    assert_equal(sell_outcome["max_favorable_60m"], 0.0, "sell no-favorable mfe")
    assert_close(sell_outcome["max_adverse_60m"], -3.0, "sell adverse")


def main():
    tests = [
        test_buy_outcome_uses_raw_forward_returns,
        test_sell_outcome_is_action_adjusted,
        test_near_close_partial_reason,
        test_missing_forward_bars_partial_reason,
        test_excursions_are_action_adjusted_and_sign_bounded,
    ]

    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print()
    print(f"All {len(tests)} rejected-signal outcome tests passed.")


if __name__ == "__main__":
    main()
