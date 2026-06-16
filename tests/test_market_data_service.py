#!/usr/bin/env python3
"""Unit tests for centralized market data access."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from types import SimpleNamespace

from services.market_data_service import MarketDataService, bar_to_dict


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


def test_default_bar_feed_uses_iex_without_sip_probe():
    client = FakeClient()
    service = MarketDataService(client=client)

    bars = service.get_bars_with_fallback("aapl", "1Min", limit=2)

    assert_equal(bars, ["iex-bar"], "default bars")
    assert_equal(len(client.calls), 1, "call count")
    assert_equal(client.calls[0][2], "iex", "default feed")
    assert_equal(service.get_feed_used("AAPL"), "iex", "tracked feed")


def test_get_bars_normalizes_sdk_and_raw_bar_attribute_names():
    class MixedBarClient:
        def get_bars(self, symbol, timeframe, feed=None, **kwargs):
            return [
                SimpleNamespace(
                    timestamp="2026-06-15T13:30:00Z",
                    open=10,
                    high=11,
                    low=9,
                    close=10.5,
                    volume=123,
                ),
                {"t": "2026-06-15T13:31:00Z", "o": 10.5, "h": 12, "l": 10, "c": 11.5, "v": 456},
            ]

    service = MarketDataService(client=MixedBarClient())

    bars = service.get_bars_with_fallback("aapl", "1Min")

    assert_equal(bars[0].t, "2026-06-15T13:30:00Z", "sdk short timestamp")
    assert_equal(bars[0].o, 10, "sdk short open")
    assert_equal(bars[0].timestamp, "2026-06-15T13:30:00Z", "sdk full timestamp")
    assert_equal(bars[1].timestamp, "2026-06-15T13:31:00Z", "raw full timestamp")
    assert_equal(bars[1].close, 11.5, "raw full close")
    assert_equal(bar_to_dict(bars[0])["close"], 10.5, "bar_to_dict normalized close")


def main():
    test_sip_subscription_error_falls_back_to_iex_and_tracks_feed()
    test_default_bar_feed_uses_iex_without_sip_probe()
    test_get_bars_normalizes_sdk_and_raw_bar_attribute_names()
    print("[OK] market data service tests passed")


if __name__ == "__main__":
    main()
