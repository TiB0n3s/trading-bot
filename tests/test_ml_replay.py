#!/usr/bin/env python3
"""Tests for replay decision-delta helpers."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ml_platform.replay import _decision_delta, _reject_bucket


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_blocking_approved_loser_counts_as_avoided_loser():
    gross, net, classification = _decision_delta(
        approved=True,
        replayed_decision="block",
        outcome={"gross_outcome_pct": -0.50},
        friction_bps=10.0,
    )

    assert_equal(gross, -0.50, "gross")
    assert_equal(net, 0.40, "net delta")
    assert_equal(classification, "avoided_loser", "classification")


def test_blocking_approved_winner_counts_as_missed_winner():
    gross, net, classification = _decision_delta(
        approved=True,
        replayed_decision="block",
        outcome={"gross_outcome_pct": 0.75},
        friction_bps=10.0,
    )

    assert_equal(gross, 0.75, "gross")
    assert_equal(net, -0.85, "net delta")
    assert_equal(classification, "missed_winner", "classification")


def test_allowing_rejected_winner_counts_as_recovered_missed_winner():
    gross, net, classification = _decision_delta(
        approved=False,
        replayed_decision="allow",
        outcome={"gross_outcome_pct": 0.60},
        friction_bps=10.0,
    )

    assert_equal(gross, 0.60, "gross")
    assert_equal(net, 0.50, "net delta")
    assert_equal(classification, "recovered_missed_winner", "classification")


def test_reject_bucket_separates_hard_gate_from_policy_relevant():
    assert_equal(
        _reject_bucket("macro_position_limit: open_position_count=8", None),
        "hard_gate_reject",
        "hard gate bucket",
    )
    assert_equal(
        _reject_bucket("buy_score=8; setup_policy=avoid", None),
        "policy_relevant_reject",
        "policy bucket",
    )


if __name__ == "__main__":
    test_blocking_approved_loser_counts_as_avoided_loser()
    print("[OK] test_blocking_approved_loser_counts_as_avoided_loser")
    test_blocking_approved_winner_counts_as_missed_winner()
    print("[OK] test_blocking_approved_winner_counts_as_missed_winner")
    test_allowing_rejected_winner_counts_as_recovered_missed_winner()
    print("[OK] test_allowing_rejected_winner_counts_as_recovered_missed_winner")
    test_reject_bucket_separates_hard_gate_from_policy_relevant()
    print("[OK] test_reject_bucket_separates_hard_gate_from_policy_relevant")
    print("\nAll 4 ML replay tests passed.")
