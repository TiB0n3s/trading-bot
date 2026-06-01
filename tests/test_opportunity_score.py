"""
Focused tests for deterministic BUY opportunity scoring.

Run:
  python3 tests/test_opportunity_score.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from opportunity_score import score_buy_opportunity


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def base_account_state():
    return {
        "trend_table": {
            "ORCL": {
                "direction": "bullish",
                "strength": "confirmed",
                "consecutive_count": 6,
            }
        },
        "momentum": {"direction": "rising", "momentum_pct": 0.3},
        "session_momentum": {
            "trend_label": "strong_uptrend",
            "trend_score": 8,
            "distance_from_vwap_pct": 0.6,
        },
        "market_bias": "buy",
        "market_bias_effective": "neutral",
        "risk_level": "medium",
        "entry_quality": "good_if_holds_gap",
        "portfolio_stress": {"portfolio_heat": "neutral"},
        "session_elapsed_minutes": 60,
        "minutes_until_close": 120,
        "setup_quality": {
            "label": "confirmed_near_vwap_recovery",
            "recommendation": "favorable",
            "score": 75,
        },
    }


def test_clean_near_vwap_setup_passes():
    result = score_buy_opportunity("ORCL", {}, base_account_state())

    assert_equal(result["decision"], "pass", "decision")
    if "session_vwap_extended" in result["reason_codes"]:
        raise AssertionError(f"unexpected vwap penalty: {result['reason_codes']}")


def test_unclassified_extended_vwap_is_blocked():
    state = base_account_state()
    state["session_momentum"]["distance_from_vwap_pct"] = 1.65
    state["setup_quality"] = {
        "label": "unclassified_transition",
        "recommendation": "watch",
        "score": 35,
    }

    result = score_buy_opportunity("ORCL", {}, state)

    assert_equal(result["decision"], "block", "decision")
    for code in ("session_vwap_extended", "setup_unclassified_transition", "unclassified_extended_vwap"):
        if code not in result["reason_codes"]:
            raise AssertionError(f"missing {code}: {result['reason_codes']}")


def main():
    tests = [
        test_clean_near_vwap_setup_passes,
        test_unclassified_extended_vwap_is_blocked,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} opportunity score tests passed.")


if __name__ == "__main__":
    main()
