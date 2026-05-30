import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(PROJECT_ROOT))

from services.policies.entry_policy import live_bias_override


def test_hard_avoid_stays_blocked():
    result = live_bias_override(
        symbol="TEST",
        bias_entry={"bias": "avoid", "avoid_type": "hard"},
        trend={},
        setup_obs={},
        prediction_gate={},
        momentum={},
    )

    assert result["effective_bias"] == "avoid_hard"
    assert result["allow_buy"] is False


def test_soft_avoid_can_be_overridden_by_strong_live_evidence():
    result = live_bias_override(
        symbol="TEST",
        bias_entry={"bias": "avoid", "avoid_type": "soft"},
        trend={
            "direction": "bullish",
            "strength": "confirmed",
            "consecutive_count": 3,
            "last_signal": "buy",
        },
        setup_obs={
            "setup_policy_action": "boost",
            "setup_label": "above_vwap_strength_continuation",
        },
        prediction_gate={
            "prediction_score": 8,
            "prediction_decision": "pass",
        },
        momentum={"direction": "rising"},
    )

    assert result["effective_bias"] == "live_override_buy"
    assert result["allow_buy"] is True


def test_soft_avoid_stays_blocked_without_strong_live_evidence():
    result = live_bias_override(
        symbol="TEST",
        bias_entry={"bias": "avoid", "avoid_type": "soft"},
        trend={
            "direction": "bullish",
            "strength": "weak",
            "consecutive_count": 2,
            "last_signal": "buy",
        },
        setup_obs={"setup_policy_action": "neutral"},
        prediction_gate={
            "prediction_score": 5,
            "prediction_decision": "watch",
        },
        momentum={"direction": "flat"},
    )

    assert result["effective_bias"] == "avoid_soft"
    assert result["allow_buy"] is False


def test_pre_market_buy_can_be_downgraded_by_bad_live_evidence():
    result = live_bias_override(
        symbol="TEST",
        bias_entry={"bias": "buy"},
        trend={
            "direction": "bearish",
            "strength": "developing",
            "consecutive_count": 3,
            "last_signal": "sell",
        },
        setup_obs={"setup_policy_action": "neutral"},
        prediction_gate={
            "prediction_score": 2,
            "prediction_decision": "block",
        },
        momentum={"direction": "falling"},
    )

    assert result["effective_bias"] == "live_override_neutral"
    assert result["allow_buy"] is False


def test_neutral_can_upgrade_on_strong_live_evidence():
    result = live_bias_override(
        symbol="TEST",
        bias_entry={"bias": "neutral"},
        trend={
            "direction": "bullish",
            "strength": "confirmed",
            "consecutive_count": 3,
            "last_signal": "buy",
        },
        setup_obs={
            "setup_policy_action": "allow",
            "setup_label": "neutral_near_vwap_balanced",
        },
        prediction_gate={
            "prediction_score": 8,
            "prediction_decision": "pass",
        },
        momentum={"direction": "rising"},
    )

    assert result["effective_bias"] == "live_override_buy"
    assert result["allow_buy"] is True


if __name__ == "__main__":
    tests = [
        test_hard_avoid_stays_blocked,
        test_soft_avoid_can_be_overridden_by_strong_live_evidence,
        test_soft_avoid_stays_blocked_without_strong_live_evidence,
        test_pre_market_buy_can_be_downgraded_by_bad_live_evidence,
        test_neutral_can_upgrade_on_strong_live_evidence,
    ]

    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print(f"\nAll {len(tests)} live-bias override tests passed.")
