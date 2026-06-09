#!/usr/bin/env python3
"""Tests for execution quality estimation."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.execution_quality_service import estimate_execution_quality  # noqa: E402


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_gt(actual, minimum, label):
    if not actual > minimum:
        raise AssertionError(f"{label}: expected > {minimum!r}, got {actual!r}")


def assert_lt(actual, maximum, label):
    if not actual < maximum:
        raise AssertionError(f"{label}: expected < {maximum!r}, got {actual!r}")


def test_tight_stable_quote_allows_execution():
    estimate = estimate_execution_quality(
        symbol="AAPL",
        action="buy",
        signal_price=100.0,
        quote_snapshot={"bid": 99.99, "ask": 100.01, "bid_size": 100, "ask_size": 100},
        account_state={"intended_qty": 10, "momentum": {"volume_state": "normal"}},
    )

    assert_equal(estimate.decision, "allow", "decision")
    assert_equal(estimate.fill_quality, "good", "fill quality")
    assert_lt(estimate.net_execution_cost_pct, 0.10, "net cost")
    assert_equal(estimate.net_edge_after_cost_pct, None, "net edge absent")


def test_wide_spread_and_thin_depth_sizes_down():
    estimate = estimate_execution_quality(
        symbol="AAPL",
        action="buy",
        signal_price=100.0,
        quote_snapshot={"bid": 99.70, "ask": 100.20, "bid_size": 10, "ask_size": 20},
        account_state={
            "intended_qty": 100,
            "momentum": {"volume_state": "thin"},
        },
    )

    assert_equal(estimate.decision, "size_down", "decision")
    assert_equal(estimate.fill_quality, "degraded", "fill quality")
    assert_gt(estimate.net_execution_cost_pct, 0.35, "net cost")
    assert_lt(estimate.top_of_book_depth_score, 0.5, "depth score")


def test_suspect_quote_blocks_execution_quality():
    estimate = estimate_execution_quality(
        symbol="AAPL",
        action="buy",
        signal_price=100.0,
        quote_snapshot={
            "bid": 98.0,
            "ask": 101.0,
            "suspect_quote": True,
            "attempts": 3,
        },
        account_state={"momentum": {"volume_state": "surge"}},
    )

    assert_equal(estimate.decision, "block", "decision")
    assert_equal(estimate.sweep_risk, "high", "sweep risk")
    assert_gt(estimate.quote_instability_score, 0.5, "instability")


def test_execution_cost_tracks_net_edge_after_cost():
    estimate = estimate_execution_quality(
        symbol="AAPL",
        action="buy",
        signal_price=100.0,
        forecast_edge_pct=0.20,
        quote_snapshot={"bid": 99.95, "ask": 100.05},
        account_state={"momentum": {"volume_state": "normal"}},
    )

    assert_equal(estimate.forecast_edge_pct, 0.20, "forecast edge")
    assert_gt(estimate.net_edge_after_cost_pct, 0.0, "net edge")


def test_toxic_vpin_blocks_execution_quality():
    estimate = estimate_execution_quality(
        symbol="AAPL",
        action="buy",
        signal_price=100.0,
        quote_snapshot={"bid": 99.99, "ask": 100.01, "bid_size": 100, "ask_size": 100},
        account_state={
            "intended_qty": 10,
            "momentum": {"volume_state": "normal"},
            "bar_pattern_features": {"vpin_toxicity_20": 0.94},
        },
    )

    assert_equal(estimate.decision, "block", "decision")
    assert_equal(estimate.fill_quality, "poor", "fill quality")
    assert_equal(estimate.sweep_risk, "high", "sweep risk")
    assert any(reason.startswith("toxic_vpin=") for reason in estimate.reasons)


def test_elevated_vpin_sizes_down_execution_quality():
    estimate = estimate_execution_quality(
        symbol="AAPL",
        action="buy",
        signal_price=100.0,
        quote_snapshot={"bid": 99.99, "ask": 100.01, "bid_size": 100, "ask_size": 100},
        account_state={
            "intended_qty": 10,
            "momentum": {"volume_state": "normal"},
            "bar_pattern_features": {"vpin_toxicity_20": 0.80},
        },
    )

    assert_equal(estimate.decision, "size_down", "decision")
    assert_equal(estimate.fill_quality, "toxic_flow", "fill quality")
    assert_equal(estimate.size_multiplier, 0.75, "size multiplier")


def test_cvd_conflict_sizes_down_execution_quality():
    estimate = estimate_execution_quality(
        symbol="AAPL",
        action="buy",
        signal_price=100.0,
        quote_snapshot={"bid": 99.99, "ask": 100.01, "bid_size": 100, "ask_size": 100},
        account_state={
            "intended_qty": 10,
            "momentum": {"volume_state": "normal"},
            "bar_pattern_features": {"cvd_price_corr_20": -0.55},
        },
    )

    assert_equal(estimate.decision, "size_down", "decision")
    assert_equal(estimate.fill_quality, "flow_conflict", "fill quality")


def main():
    tests = [
        test_tight_stable_quote_allows_execution,
        test_wide_spread_and_thin_depth_sizes_down,
        test_suspect_quote_blocks_execution_quality,
        test_execution_cost_tracks_net_edge_after_cost,
        test_toxic_vpin_blocks_execution_quality,
        test_elevated_vpin_sizes_down_execution_quality,
        test_cvd_conflict_sizes_down_execution_quality,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} execution quality service tests passed.")


if __name__ == "__main__":
    main()
