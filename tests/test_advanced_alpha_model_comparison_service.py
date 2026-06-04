#!/usr/bin/env python3
"""Tests for advanced alpha model comparison diagnostics."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.advanced_alpha_model_comparison_service import (  # noqa: E402
    build_advanced_alpha_model_comparison_payload,
)


def test_asymmetric_filter_reduces_false_positive_exposure():
    rows = [
        {
            "long_opportunity_score": 80,
            "forward_return_pct": 1.2,
            "triple_barrier_label": 1,
            "trend_scan_label": 1,
            "cvd_divergence_label": "bullish_absorption",
            "vpin_toxicity_20": 0.2,
        },
        {
            "long_opportunity_score": 75,
            "forward_return_pct": -0.9,
            "triple_barrier_label": -1,
            "trend_scan_label": -1,
            "cvd_divergence_label": "bearish_distribution",
            "vpin_toxicity_20": 0.4,
        },
        {
            "long_opportunity_score": 55,
            "forward_return_pct": -0.3,
            "triple_barrier_label": -1,
            "trend_scan_label": 1,
            "cvd_divergence_label": "neutral",
            "vpin_toxicity_20": 0.2,
        },
        {
            "long_opportunity_score": 45,
            "forward_return_pct": 0.4,
            "triple_barrier_label": 1,
            "trend_scan_label": 1,
            "cvd_divergence_label": "bullish_absorption",
            "vpin_toxicity_20": 0.2,
        },
    ]

    payload = build_advanced_alpha_model_comparison_payload(rows)
    data = payload.to_dict()
    by_name = {profile["name"]: profile for profile in data["profiles"]}

    assert data["report_version"] == "advanced_alpha_model_comparison_v1"
    assert data["runtime_effect"] == "diagnostic_only_no_live_authority"
    assert data["summary"]["authority_ready"] is False
    assert by_name["standard_score_threshold"]["trades_taken"] == 3
    assert by_name["asymmetric_false_positive_guard"]["trades_taken"] == 1
    assert data["summary"]["false_positive_reduction"] == 2


def test_empty_comparison_payload_is_stable():
    payload = build_advanced_alpha_model_comparison_payload([])
    data = payload.to_dict()

    assert data["rows"] == 0
    assert data["rows_with_outcome"] == 0
    assert data["summary"]["authority_ready"] is False
    assert all(profile["trades_taken"] == 0 for profile in data["profiles"])


def main():
    tests = [
        test_asymmetric_filter_reduces_false_positive_exposure,
        test_empty_comparison_payload_is_stable,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} advanced alpha comparison tests passed.")


if __name__ == "__main__":
    main()
