#!/usr/bin/env python3
"""Unit tests for centralized market data access."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.market_data_service import MarketDataService


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


class FakeClient:
    def __init__(self):
        self.calls = []

    def get_bars(self, symbol, timeframe, feed=None, **kwargs):
        self.calls.append((symbol, timeframe, feed, kwargs))
        if feed == "sip":
            raise RuntimeError("subscription not permitted")
        return ["iex-bar"]


def test_sip_subscription_error_falls_back_to_iex_and_tracks_feed():
    client = FakeClient()
    service = MarketDataService(client=client)

    bars = service.get_bars_with_fallback("aapl", "1Min", feed="sip", limit=2)

    assert_equal(bars, ["iex-bar"], "fallback bars")
    assert_equal(client.calls[0][2], "sip", "first feed")
    assert_equal(client.calls[1][2], "iex", "fallback feed")
    assert_equal(service.get_feed_used("AAPL"), "iex", "tracked feed")


def main():
    test_sip_subscription_error_falls_back_to_iex_and_tracks_feed()
    print("[OK] market data service tests passed")


if __name__ == "__main__":
    main()
