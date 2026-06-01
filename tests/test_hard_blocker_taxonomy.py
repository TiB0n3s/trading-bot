#!/usr/bin/env python3
"""Tests for strict hard-blocker taxonomy."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.hard_blocker_taxonomy import (
    HARD_BLOCKER_TAXONOMY_VERSION,
    classify_hard_blocker,
    hard_blocker_contract,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_strict_domains_are_hard_blockers():
    assert_equal(classify_hard_blocker("stale_signal").domain, "stale_signal", "stale")
    assert_equal(classify_hard_blocker("second_look", "spread too wide").domain, "liquidity_or_spread", "spread")
    assert_equal(classify_hard_blocker("affordability").domain, "broker_or_account_constraint", "account")
    assert_equal(classify_hard_blocker("daily_loss_limit").domain, "max_risk", "risk")
    assert_equal(classify_hard_blocker("macro_risk").domain, "broken_market_regime", "regime")


def test_soft_edge_gates_are_not_hard_blockers():
    classification = classify_hard_blocker("confidence_gate", "Claude low confidence")

    assert_equal(classification.is_hard_blocker, False, "not hard")
    assert_equal(classification.domain, None, "domain")


def test_contract_is_versioned_and_limited():
    contract = hard_blocker_contract()

    assert_equal(contract["taxonomy_version"], HARD_BLOCKER_TAXONOMY_VERSION, "version")
    assert_equal(
        contract["hard_blocker_domains"],
        [
            "broken_market_regime",
            "broker_or_account_constraint",
            "liquidity_or_spread",
            "max_risk",
            "stale_signal",
        ],
        "domains",
    )


def main():
    tests = [
        test_strict_domains_are_hard_blockers,
        test_soft_edge_gates_are_not_hard_blockers,
        test_contract_is_versioned_and_limited,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} hard blocker taxonomy tests passed.")


if __name__ == "__main__":
    main()
