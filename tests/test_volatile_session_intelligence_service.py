#!/usr/bin/env python3
"""Tests for volatile-session intelligence diagnostics."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.volatile_session_intelligence_service import (
    asymmetric_penalty_probe,
    build_volatile_session_intelligence_payload,
    filter_rows_by_market_time,
)


class FakeBarPatternRepo:
    def __init__(self):
        self.rows = []
        for minute in range(60):
            self.rows.append(
                {
                    "symbol": "QQQ",
                    "bar_timestamp": f"2026-06-08T13:{minute:02d}:00+00:00",
                    "timeframe": "1m",
                    "close": 100.0 - (minute * 0.05),
                    "volume": 1000.0,
                }
            )

    def volume_clock_source_rows(self, **kwargs):
        return list(self.rows)

    def latest_for_symbol(self, symbol, *, timeframe="1m"):
        return {
            "symbol": symbol,
            "bar_timestamp": "2026-06-08T13:59:00+00:00",
            "atr_20_pct": 0.012,
            "vpin_toxicity_20": 0.82,
            "cumulative_volume_delta": -12000,
        }


def test_filter_rows_by_market_time_uses_eastern_clock():
    rows = [
        {"bar_timestamp": "2026-06-08T13:29:00+00:00"},
        {"bar_timestamp": "2026-06-08T13:30:00+00:00"},
        {"bar_timestamp": "2026-06-08T14:00:00+00:00"},
        {"bar_timestamp": "2026-06-08T14:01:00+00:00"},
    ]

    filtered = filter_rows_by_market_time(
        rows,
        start_time="09:30",
        end_time="10:00",
    )

    assert [row["bar_timestamp"] for row in filtered] == [
        "2026-06-08T13:30:00+00:00",
        "2026-06-08T14:00:00+00:00",
    ]


def test_asymmetric_penalty_probe_validates_10x_pressure():
    probe = asymmetric_penalty_probe(false_positive_penalty=10.0)

    assert probe["status"] == "active"
    assert probe["configured_penalty"] == 10.0
    assert probe["gradient_penalty_ratio"] >= 9.5


def test_volatile_session_payload_combines_penalty_vpin_and_transformer():
    def fake_transformer(**kwargs):
        return {
            "decision": "size_down",
            "size_multiplier": 0.65,
            "probability": 0.41,
            "reason": "test macro shock size down",
        }

    payload = build_volatile_session_intelligence_payload(
        target_date="2026-06-08",
        symbols=["QQQ"],
        base_dir=ROOT,
        repo=FakeBarPatternRepo(),
        transformer_evaluator=fake_transformer,
        bucket_volume=5000,
        window_buckets=3,
        start_time="09:30",
        end_time="10:00",
    )

    assert payload["report_version"] == "volatile_session_intelligence_v1"
    assert payload["runtime_effect"] == "diagnostic_only_no_live_authority"
    assert payload["asymmetric_penalty"]["status"] == "active"
    assert payload["summary"]["transformer_size_down_symbols"] == 1
    assert payload["symbols"][0]["window_rows"] == 30
    assert payload["symbols"][0]["vpin_bucket_count"] > 0


if __name__ == "__main__":
    tests = [
        test_filter_rows_by_market_time_uses_eastern_clock,
        test_asymmetric_penalty_probe_validates_10x_pressure,
        test_volatile_session_payload_combines_penalty_vpin_and_transformer,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} volatile-session intelligence tests passed.")
