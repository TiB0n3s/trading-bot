#!/usr/bin/env python3
"""Tests for live quote quality provider diagnostics."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.live_quote_quality_service import (  # noqa: E402
    LiveQuoteQualityService,
    LiveQuoteQualityThresholds,
)
from services.market_data_parity_service import MarketDataParityService  # noqa: E402


class FakeProvider:
    def __init__(self, quote):
        self.quote = quote

    def get_latest_quote(self, symbol):
        return self.quote

    def latest_quote_summary(self, symbol):
        return self.quote


def test_live_quote_quality_passes_with_two_consistent_providers():
    service = LiveQuoteQualityService(
        MarketDataParityService(
            alpaca_market_data=FakeProvider({"bid": 100.0, "ask": 100.2}),
            polygon_market_data=FakeProvider({"bid": 100.01, "ask": 100.21}),
            webull_market_data=FakeProvider({"bid": 0.0, "ask": 0.0}),
        )
    )

    report = service.assess("aapl")

    assert report.ok is True
    assert report.symbol == "AAPL"
    assert report.available_provider_count == 2
    assert report.available_providers == ["alpaca", "polygon"]
    assert report.unavailable_providers == ["webull"]


def test_live_quote_quality_warns_on_wide_provider_mid_range():
    service = LiveQuoteQualityService(
        MarketDataParityService(
            alpaca_market_data=FakeProvider({"bid": 100.0, "ask": 100.2}),
            polygon_market_data=FakeProvider({"bid": 101.0, "ask": 101.2}),
            webull_market_data=FakeProvider({"bid": 100.1, "ask": 100.3}),
        ),
        thresholds=LiveQuoteQualityThresholds(max_mid_range_pct=0.10),
    )

    report = service.assess("MSFT")

    assert report.ok is False
    assert "provider_mid_range_too_wide" in report.blockers


def main():
    tests = [
        test_live_quote_quality_passes_with_two_consistent_providers,
        test_live_quote_quality_warns_on_wide_provider_mid_range,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} live quote quality service tests passed.")


if __name__ == "__main__":
    main()
