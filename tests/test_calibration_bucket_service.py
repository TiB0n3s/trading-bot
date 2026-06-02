#!/usr/bin/env python3
"""Tests for realized calibration bucket summaries."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.calibration_bucket_service import build_calibration_bucket_payload


def test_calibration_buckets_compute_realized_win_ev_and_error_counts():
    payload = build_calibration_bucket_payload(
        [
            {
                "approved": 1,
                "setup_label": "breakout",
                "market_regime": "trend_expansion",
                "decision_hour": "10",
                "volatility_chase_risk": "low",
                "realized_return_pct": 0.6,
                "mfe_pct": 1.0,
                "max_adverse_excursion_pct": -0.2,
            },
            {
                "approved": 1,
                "setup_label": "breakout",
                "market_regime": "trend_expansion",
                "decision_hour": "10",
                "volatility_chase_risk": "low",
                "realized_return_pct": -0.3,
                "mfe_pct": 0.2,
                "max_adverse_excursion_pct": -0.6,
            },
            {
                "approved": 0,
                "setup_label": "breakout",
                "market_regime": "trend_expansion",
                "decision_hour": "10",
                "volatility_chase_risk": "low",
                "rejected_return_eod": 0.4,
                "rejected_max_favorable_60m": 0.9,
                "rejected_max_adverse_60m": -0.1,
            },
        ],
        min_sample_size=2,
    )

    bucket = payload.buckets[0]
    assert payload.summary["report_version"] == "calibration_buckets_v1"
    assert payload.summary["ready_bucket_count"] == 1
    assert bucket["sample_size"] == 3
    assert bucket["win_rate"] == 0.6667
    assert bucket["false_positive_count"] == 1
    assert bucket["false_negative_count"] == 1


def main():
    tests = [test_calibration_buckets_compute_realized_win_ev_and_error_counts]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} calibration bucket tests passed.")


if __name__ == "__main__":
    main()
