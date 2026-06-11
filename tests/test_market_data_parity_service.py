#!/usr/bin/env python3
"""Tests for Alpaca-vs-Polygon parity diagnostics."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.market_data_parity_service import (  # noqa: E402
    MARKET_DATA_PARITY_VERSION,
    MarketDataParityService,
    normalize_quote,
)


class FakeAlpaca:
    def get_latest_quote(self, symbol):
        return {"bp": 100.0, "ap": 100.2, "t": "alpaca-ts"}

    def get_bars_with_fallback(self, symbol, timeframe, **kwargs):
        return [
            {
                "open": 100,
                "high": 103,
                "low": 99,
                "close": 102,
                "volume": 1000,
                "timestamp": "2026-06-01",
            }
        ]


class FakePolygon:
    def latest_quote_summary(self, symbol):
        return {"bid": 100.1, "ask": 100.3, "timestamp": "polygon-ts"}

    def aggregate_bars(self, symbol, **kwargs):
        return {
            "status": "OK",
            "results": [
                {
                    "o": 100.0,
                    "h": 103.5,
                    "l": 99.0,
                    "c": 101.5,
                    "v": 1100,
                    "t": 123,
                }
            ],
        }


def test_normalize_quote_accepts_common_bid_ask_names():
    quote = normalize_quote("test", {"bid_price": 10, "ask_price": 10.1})

    assert quote["available"] is True
    assert quote["mid"] == 10.05
    assert round(quote["spread_pct"], 4) == round(0.1 / 10.05 * 100, 4)


def test_normalize_quote_rejects_zero_or_inverted_quotes():
    zero_ask = normalize_quote("alpaca", {"bid_price": 276.16, "ask_price": 0.0})
    inverted = normalize_quote("test", {"bid_price": 10.2, "ask_price": 10.1})

    assert zero_ask["available"] is False
    assert zero_ask["mid"] is None
    assert zero_ask["spread_pct"] is None
    assert inverted["available"] is False


def test_latest_quote_parity_computes_deltas():
    service = MarketDataParityService(
        alpaca_market_data=FakeAlpaca(),
        polygon_market_data=FakePolygon(),
    )

    payload = service.latest_quote_parity("aapl")

    assert payload["version"] == MARKET_DATA_PARITY_VERSION
    assert payload["runtime_effect"] == "diagnostic_only_no_live_authority"
    assert payload["symbol"] == "AAPL"
    assert payload["status"] == "ok"
    assert round(payload["mid_diff"], 4) == -0.1
    assert payload["alpaca"]["available"] is True
    assert payload["polygon"]["available"] is True


def test_daily_bar_parity_computes_field_diffs():
    service = MarketDataParityService(
        alpaca_market_data=FakeAlpaca(),
        polygon_market_data=FakePolygon(),
    )

    payload = service.daily_bar_parity("aapl", "2026-06-01")

    assert payload["status"] == "ok"
    assert payload["diffs"]["close"]["diff"] == 0.5
    assert payload["diffs"]["volume"]["diff"] == -100


def main():
    tests = [
        test_normalize_quote_accepts_common_bid_ask_names,
        test_normalize_quote_rejects_zero_or_inverted_quotes,
        test_latest_quote_parity_computes_deltas,
        test_daily_bar_parity_computes_field_diffs,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} market-data parity service tests passed.")


if __name__ == "__main__":
    main()
