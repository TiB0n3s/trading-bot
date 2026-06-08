#!/usr/bin/env python3
"""Tests for volume-clock VPIN bucketization."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.volume_clock_vpin_service import build_volume_clock_vpin_payload


def _rows():
    rows = []
    for i in range(20):
        rows.append(
            {
                "symbol": "AAPL",
                "bar_timestamp": f"2026-06-04T14:{i:02d}:00+00:00",
                "close": 100 + (i * 0.10),
                "volume": 1000,
            }
        )
    return rows


def test_volume_clock_vpin_builds_equal_volume_buckets():
    payload = build_volume_clock_vpin_payload(
        rows=_rows(),
        symbol="AAPL",
        target_date="2026-06-04",
        bucket_volume=5000,
        window_buckets=3,
    ).to_dict()

    assert payload["report_version"] == "volume_clock_vpin_v1"
    assert payload["runtime_effect"] == "research_report_only_no_live_authority"
    assert payload["summary"]["bucket_count"] == 4
    assert payload["buckets"][0]["volume"] == 5000
    assert payload["summary"]["latest_vpin"] is not None
    assert payload["summary"]["true_trade_level"] is False


def test_volume_clock_vpin_handles_insufficient_volume():
    payload = build_volume_clock_vpin_payload(
        rows=[{"bar_timestamp": "2026-06-04T14:00:00+00:00", "close": 100, "volume": 100}],
        symbol="AAPL",
        target_date="2026-06-04",
        bucket_volume=5000,
    ).to_dict()

    assert payload["summary"]["bucket_count"] == 0
    assert payload["summary"]["toxicity_bucket"] == "insufficient_buckets"


if __name__ == "__main__":
    tests = [
        test_volume_clock_vpin_builds_equal_volume_buckets,
        test_volume_clock_vpin_handles_insufficient_volume,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} volume-clock VPIN tests passed.")
