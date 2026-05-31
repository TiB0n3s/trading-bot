#!/usr/bin/env python3
"""Tests for portfolio-level duplicate-risk decisioning."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.portfolio_decision_service import evaluate_portfolio_decision


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_gt(actual, minimum, label):
    if not actual > minimum:
        raise AssertionError(f"{label}: expected > {minimum!r}, got {actual!r}")


def test_semiconductor_stack_is_duplicate_risk():
    decision = evaluate_portfolio_decision(
        symbol="TSM",
        action="buy",
        account_state={
            "balance": 100_000,
            "proposed_position_size_pct": 2.0,
            "open_positions": [
                {"symbol": "NVDA", "qty": 10, "market_value": 7_000},
                {"symbol": "AMD", "qty": 30, "market_value": 5_000},
                {"symbol": "AVGO", "qty": 5, "market_value": 5_500},
            ],
        },
    )

    assert_equal(decision.decision, "block", "decision")
    assert_equal(decision.crowded_theme, "mega_cap_tech", "crowded theme")
    assert_gt(decision.duplicate_risk_score, 0.7, "duplicate risk")
    assert_equal("AMD" in decision.overlap_symbols, True, "overlap AMD")
    assert_equal("NVDA" in decision.overlap_symbols, True, "overlap NVDA")


def test_diversifying_buy_allows_when_limits_clean():
    decision = evaluate_portfolio_decision(
        symbol="PFE",
        action="buy",
        account_state={
            "balance": 100_000,
            "proposed_position_size_pct": 1.0,
            "open_positions": [
                {"symbol": "XOM", "qty": 20, "market_value": 3_000},
                {"symbol": "JPM", "qty": 10, "market_value": 2_500},
            ],
        },
    )

    assert_equal(decision.decision, "allow", "decision")
    assert_equal(decision.crowded_theme, None, "crowded theme")
    assert_equal(decision.overlap_symbols, [], "overlap")


def test_sell_is_not_applicable():
    decision = evaluate_portfolio_decision(
        symbol="NVDA",
        action="sell",
        account_state={"balance": 100_000},
    )

    assert_equal(decision.decision, "not_applicable", "decision")
    assert_equal(decision.incremental_position_pct, 0.0, "incremental pct")


def main():
    tests = [
        test_semiconductor_stack_is_duplicate_risk,
        test_diversifying_buy_allows_when_limits_clean,
        test_sell_is_not_applicable,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} portfolio decision service tests passed.")


if __name__ == "__main__":
    main()
