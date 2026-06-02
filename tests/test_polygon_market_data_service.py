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


def main():
    tests = [
        test_polygon_latest_quote_summary_uses_injected_transport,
        test_polygon_requires_api_key_before_request,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} Polygon market data service tests passed.")


if __name__ == "__main__":
    main()
