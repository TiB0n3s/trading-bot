#!/usr/bin/env python3
"""Tests for paper-only historical-bar meta-label authority."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.historical_bar_meta_label_authority_service import (  # noqa: E402
    evaluate_historical_bar_meta_label_authority,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def _strategy(**overrides):
    strategy = {
        "status": "paper_ready",
        "master_confidence_score": 78.0,
        "paper_recommendation": "paper_size_candidate",
        "baseline_delta": 8.0,
        "liquidity_stress_bucket": "normal",
        "paper_position_size_pct": 1.4,
    }
    strategy.update(overrides)
    return strategy


def _config(**overrides):
    config = {
        "enabled": True,
        "min_veto_score": 65.0,
        "min_approve_score": 65.0,
        "min_size_increase_score": 75.0,
        "min_baseline_delta": 0.0,
        "max_position_size_pct": 1.5,
        "can_veto": True,
    }
    config.update(overrides)
    return config


def test_meta_label_approves_rejected_layer_one_candidate():
    account_state = {"historical_bar_paper_strategy": _strategy()}
    outcome = evaluate_historical_bar_meta_label_authority(
        symbol="AAPL",
        action="buy",
        decision={"approved": False, "position_size_pct": 1.0},
        account_state=account_state,
        execution_mode="paper",
        config=_config(),
    )

    assert_equal(outcome["allowed"], True, "allowed")
    assert_equal(outcome["effect"], "paper_approval", "effect")
    assert_equal(outcome["position_size_pct"], 1.4, "size")


def test_meta_label_increases_size_for_approved_candidate():
    account_state = {"historical_bar_paper_strategy": _strategy()}
    outcome = evaluate_historical_bar_meta_label_authority(
        symbol="AAPL",
        action="buy",
        decision={"approved": True, "position_size_pct": 1.0},
        account_state=account_state,
        execution_mode="paper",
        config=_config(),
    )

    assert_equal(outcome["allowed"], True, "allowed")
    assert_equal(outcome["effect"], "size_increase", "effect")
    assert_equal(outcome["position_size_pct"], 1.4, "size")


def test_meta_label_vetoes_weak_candidate():
    account_state = {
        "historical_bar_paper_strategy": _strategy(
            master_confidence_score=52.0,
            paper_recommendation="paper_avoid",
            paper_position_size_pct=0.0,
        )
    }
    outcome = evaluate_historical_bar_meta_label_authority(
        symbol="AAPL",
        action="buy",
        decision={"approved": True, "position_size_pct": 1.0},
        account_state=account_state,
        execution_mode="paper",
        config=_config(),
    )

    assert_equal(outcome["allowed"], True, "allowed")
    assert_equal(outcome["effect"], "veto", "effect")
    assert_equal(outcome["position_size_pct"], 0.0, "size")


def test_meta_label_does_not_apply_outside_paper():
    account_state = {"historical_bar_paper_strategy": _strategy()}
    outcome = evaluate_historical_bar_meta_label_authority(
        symbol="AAPL",
        action="buy",
        decision={"approved": False, "position_size_pct": 1.0},
        account_state=account_state,
        execution_mode="cash_full",
        config=_config(),
    )

    assert_equal(outcome["allowed"], False, "allowed")
    assert_equal(outcome["effect"], "none", "effect")


def main():
    tests = [
        test_meta_label_approves_rejected_layer_one_candidate,
        test_meta_label_increases_size_for_approved_candidate,
        test_meta_label_vetoes_weak_candidate,
        test_meta_label_does_not_apply_outside_paper,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} historical-bar meta-label authority tests passed.")


if __name__ == "__main__":
    main()
