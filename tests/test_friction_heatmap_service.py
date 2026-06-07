#!/usr/bin/env python3
"""Tests for LSI friction heatmap diagnostics."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.friction_heatmap_service import build_friction_heatmap_payload  # noqa: E402


def test_friction_heatmap_counts_toxic_stopouts_avoided():
    rows = [
        {
            "long_opportunity_score": 82,
            "forward_return_pct": -0.8,
            "triple_barrier_label": -1,
            "trend_scan_label": 1,
            "cvd_divergence_label": "neutral",
            "vpin_toxicity_20": 0.96,
            "bid_ask_spread_pct": 0.20,
            "slippage_estimate_pct": 0.12,
        },
        {
            "long_opportunity_score": 78,
            "forward_return_pct": -0.5,
            "triple_barrier_label": -1,
            "trend_scan_label": -1,
            "cvd_divergence_label": "bearish_distribution",
            "vpin_toxicity_20": 0.55,
            "liquidity_sweep_risk": 0.80,
        },
        {
            "long_opportunity_score": 76,
            "forward_return_pct": 1.1,
            "triple_barrier_label": 1,
            "trend_scan_label": 1,
            "cvd_divergence_label": "bullish_absorption",
            "vpin_toxicity_20": 0.25,
        },
        {
            "long_opportunity_score": 58,
            "forward_return_pct": -0.2,
            "triple_barrier_label": -1,
            "trend_scan_label": 1,
            "cvd_divergence_label": "neutral",
            "vpin_toxicity_20": 0.15,
        },
    ]

    payload = build_friction_heatmap_payload(rows)
    data = payload.to_dict()

    assert data["report_version"] == "friction_heatmap_v1"
    assert data["runtime_effect"] == "diagnostic_only_no_live_authority"
    assert data["rows_with_outcome"] == 4
    assert data["summary"]["authority_ready"] is False
    assert data["summary"]["symmetric_toxic_stopouts"] == 2
    assert data["summary"]["asymmetric_toxic_stopouts_avoided"] == 2
    assert data["summary"]["asymmetric_lsi_scale_down_candidates"] >= 0

    by_profile_bucket = {
        (cell["profile"], cell["liquidity_stress_bucket"]): cell
        for cell in data["heatmap"]
    }
    symmetric_toxic = sum(
        cell["toxic_stopouts"]
        for key, cell in by_profile_bucket.items()
        if key[0] == "symmetric_score_threshold"
    )
    assert symmetric_toxic == 2
    assert by_profile_bucket[("asymmetric_lsi_guard", "severe")]["trades_taken"] == 0


def test_empty_friction_heatmap_is_stable():
    payload = build_friction_heatmap_payload([])
    data = payload.to_dict()

    assert data["rows"] == 0
    assert data["rows_with_outcome"] == 0
    assert data["summary"]["symmetric_toxic_stopouts"] == 0
    assert len(data["heatmap"]) == 10


def main():
    tests = [
        test_friction_heatmap_counts_toxic_stopouts_avoided,
        test_empty_friction_heatmap_is_stable,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} friction heatmap tests passed.")


if __name__ == "__main__":
    main()
