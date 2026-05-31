#!/usr/bin/env python3
"""Tests for calibrated confidence contract."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.confidence_calibration_service import build_calibrated_confidence


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_close(actual, expected, label, tolerance=0.0001):
    if abs(actual - expected) > tolerance:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_calibrated_confidence_uses_realized_bucket_stats():
    result = build_calibrated_confidence(
        account_state={
            "setup_quality": {
                "label": "near_vwap_recovery",
                "confidence": "high",
            },
            "prediction_gate": {
                "ml_prediction_bucket": "high_55_plus",
                "ml_prediction_confidence": "medium",
            },
            "market_regime": {"composite_regime": "trend_expansion"},
            "decision_ts": "2026-05-31T09:45:00",
            "calibration_stats": {
                "setup_quality": {
                    "by_bucket": {
                        "near_vwap_recovery|trend_expansion": {
                            "sample_size": 28,
                            "predicted_win_rate": 0.60,
                            "realized_win_rate": 0.64,
                            "avg_realized_pnl_pct": 0.42,
                            "avg_mfe_pct": 0.90,
                            "avg_mae_pct": -0.35,
                            "precision_by_setup_type": 0.66,
                            "precision_by_regime": 0.61,
                            "precision_by_time_of_day": 0.58,
                        }
                    }
                }
            },
        },
        decision={"confidence": "high"},
    ).to_dict()

    setup = result["sources"]["setup_quality"]
    assert_equal(result["primary_source"], "setup_quality", "primary source")
    assert_equal(result["confidence_quality"], "medium", "quality")
    assert_close(setup["realized_win_rate"], 0.64, "realized win rate")
    assert_close(setup["calibration_error"], 0.04, "calibration error")
    assert_close(setup["expected_move_r"], 1.2, "expected move r")
    assert_close(setup["precision_by_regime"], 0.61, "regime precision")


def test_missing_stats_uses_raw_label_prior_and_marks_uncalibrated():
    result = build_calibrated_confidence(
        account_state={
            "setup_quality": {"label": "unknown", "confidence": "medium"},
            "prediction_gate": {"ml_prediction_confidence": "low"},
        },
        decision={"confidence": "high"},
    ).to_dict()

    claude = result["sources"]["claude"]
    assert_equal(result["confidence_quality"], "uncalibrated_prior", "quality")
    assert_close(claude["predicted_win_rate"], 0.62, "raw high prior")
    assert_equal(claude["realized_win_rate"], None, "missing realized")
    assert_equal(claude["fallback_reason"], "raw_confidence_prior", "fallback")


def main():
    tests = [
        test_calibrated_confidence_uses_realized_bucket_stats,
        test_missing_stats_uses_raw_label_prior_and_marks_uncalibrated,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} confidence calibration service tests passed.")


if __name__ == "__main__":
    main()
