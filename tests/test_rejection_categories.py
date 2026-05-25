#!/usr/bin/env python3
"""Tests for stable rejection category constants."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import rejection_categories as rc


def test_all_categories_are_strings():
    assert rc.ALL_REJECTION_CATEGORIES
    for category in rc.ALL_REJECTION_CATEGORIES:
        assert isinstance(category, str)
        assert category
        assert category == category.lower()
        assert " " not in category


def test_required_categories_exist():
    required = {
        rc.MARKET_HOURS,
        rc.DAILY_LOSS_LIMIT,
        rc.SYMBOL_NOT_APPROVED,
        rc.MACRO_RISK,
        rc.SETUP_POLICY,
        rc.COOLDOWN,
        rc.SELL_TO_BUY_CHURN,
        rc.AFFORDABILITY,
        rc.PRICE_SANITY,
        rc.PAYLOAD_VALIDATION,
        rc.BROKER_REJECTED,
        rc.CLAUDE_REJECTED,
        rc.ORDER_QTY_ZERO,
        rc.UNKNOWN_ERROR,
    }

    missing = required - rc.ALL_REJECTION_CATEGORIES
    assert not missing, f"Missing categories: {sorted(missing)}"


def test_no_duplicate_category_values():
    values = list(rc.ALL_REJECTION_CATEGORIES)
    assert len(values) == len(set(values))


def test_format_rejection_reason_preserves_category_prefix():
    assert (
        rc.format_rejection_reason("churn_price", "not enough improvement")
        == "churn_price: not enough improvement"
    )
    assert (
        rc.format_rejection_reason("market_bias_avoid", "avoid")
        == "market_bias_avoid: avoid"
    )


def test_reason_category_extracts_normalized_category():
    assert rc.reason_category("churn_window: wait") == "churn_window"
    assert rc.reason_category("macro_risk: blocked") == rc.MACRO_RISK


if __name__ == "__main__":
    test_all_categories_are_strings()
    test_required_categories_exist()
    test_no_duplicate_category_values()
    test_format_rejection_reason_preserves_category_prefix()
    test_reason_category_extracts_normalized_category()
    print("[OK] rejection category constants")
