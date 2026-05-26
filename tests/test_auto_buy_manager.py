"""
Focused tests for internal auto-buy candidate scoring.

Run:
  python3 tests/test_auto_buy_manager.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from auto_buy_manager import evaluate_auto_buy_candidate
from auto_buy_manager import maybe_execute_auto_buy


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def strong_session():
    return {
        "trend_label": "strong_uptrend",
        "trend_score": 7,
        "session_return_pct": 1.2,
        "momentum_5m_pct": 0.2,
        "momentum_15m_pct": 0.45,
        "momentum_30m_pct": 0.65,
        "distance_from_vwap_pct": 0.4,
    }


def favorable_feature():
    return {
        "id": 123,
        "setup_label": "near_vwap_weak_strength_followthrough",
        "setup_recommendation": "favorable",
        "setup_score": 88,
        "relative_strength_5m": 0.4,
        "ret_5m": 0.2,
        "ret_15m": 0.3,
        "distance_from_vwap": 0.2,
    }


def buy_context():
    return {
        "bias": "buy",
        "entry_quality": "good_if_holds_gap",
        "risk_level": "medium",
        "avoid_type": None,
    }


def test_strong_internal_candidate_scores_as_buy_candidate():
    result = evaluate_auto_buy_candidate(
        symbol="AMZN",
        session=strong_session(),
        feature=favorable_feature(),
        context=buy_context(),
        held=set(),
    )

    assert_equal(result["decision"], "strong_buy_candidate", "decision")
    assert_equal(result["severity"], "high", "severity")


def test_held_symbol_is_skipped():
    result = evaluate_auto_buy_candidate(
        symbol="AMZN",
        session=strong_session(),
        feature=favorable_feature(),
        context=buy_context(),
        held={"AMZN"},
    )

    assert_equal(result["decision"], "skip", "decision")
    assert_equal(result["severity"], "held", "severity")


def test_negative_session_blocks_candidate():
    session = strong_session()
    session["trend_label"] = "downtrend"
    session["trend_score"] = -6
    session["momentum_15m_pct"] = -0.5

    result = evaluate_auto_buy_candidate(
        symbol="AMZN",
        session=session,
        feature=favorable_feature(),
        context=buy_context(),
        held=set(),
    )

    assert_equal(result["decision"], "skip", "decision")
    assert_equal(result["severity"], "blocked", "severity")


def test_live_buy_requires_market_open_and_env_flag():
    candidate = {
        "symbol": "AMZN",
        "decision": "strong_buy_candidate",
        "risk_level": "medium",
    }

    order = maybe_execute_auto_buy(candidate, market_open=False, live_requested=False)

    assert_equal(order, None, "order")
    assert_equal(candidate["live_block_reason"], "live not requested or AUTO_BUY_LIVE_BUYS is false", "block reason")


def main():
    tests = [
        test_strong_internal_candidate_scores_as_buy_candidate,
        test_held_symbol_is_skipped,
        test_negative_session_blocks_candidate,
        test_live_buy_requires_market_open_and_env_flag,
    ]

    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print()
    print(f"All {len(tests)} auto-buy manager tests passed.")


if __name__ == "__main__":
    main()
