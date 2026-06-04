#!/usr/bin/env python3
"""Tests for Polygon validation adapter."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.polygon_market_data_service import PolygonMarketDataService  # noqa: E402


def test_polygon_latest_quote_summary_uses_injected_transport():
    calls = []

    def transport(request):
        calls.append(request)
        return {
            "status": "OK",
            "results": {
                "bid_price": 100.0,
                "ask_price": 100.2,
            },
        }

    service = PolygonMarketDataService(api_key="test-key", transport=transport)
    summary = service.latest_quote_summary("aapl")

    assert summary["symbol"] == "AAPL"
    assert summary["provider"] == "polygon"
    assert round(summary["spread"], 4) == 0.2
    assert round(summary["spread_pct"], 4) == round(0.2 / 100.1 * 100, 4)
    assert "apiKey=test-key" in calls[0].url


def test_polygon_requires_api_key_before_request():
    service = PolygonMarketDataService(api_key="", transport=lambda request: {})

    try:
        service.latest_quote("AAPL")
    except RuntimeError as exc:
        assert "POLYGON_API_KEY" in str(exc)
    else:
        raise AssertionError("expected missing key error")


def test_polygon_aggregate_bar_dicts_normalizes_results():
    calls = []

    def transport(request):
        calls.append(request)
        return {
            "status": "OK",
            "results": [
                {"t": 1780407000000, "o": 100.0, "h": 101.0, "l": 99.5, "c": 100.5, "v": 12345, "vw": 100.3},
                {"t": 1780407300000, "o": 100.5, "h": 102.0, "l": 100.2, "c": 101.8, "v": 23456},
            ],
        }

    service = PolygonMarketDataService(api_key="test-key", transport=transport)
    bars = service.aggregate_bar_dicts("aapl", from_date="2026-06-02", to_date="2026-06-02")

    assert len(bars) == 2
    assert bars[0]["timestamp"].startswith("2026-06-02T")
    assert bars[0]["open"] == 100.0
    assert bars[0]["vwap"] == 100.3
    assert bars[1]["close"] == 101.8
    assert bars[1]["vwap"] == 101.8
    assert "/v2/aggs/ticker/AAPL/range/5/minute/2026-06-02/2026-06-02" in calls[0].url


def main():
    tests = [
        test_polygon_latest_quote_summary_uses_injected_transport,
        test_polygon_requires_api_key_before_request,
        test_polygon_aggregate_bar_dicts_normalizes_results,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} Polygon market data service tests passed.")


if __name__ == "__main__":
    main()
