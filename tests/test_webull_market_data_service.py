#!/usr/bin/env python3
"""Tests for read-only Webull market-data integration."""

from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src" / "trading_bot"))

from services.market_data_parity_service import MarketDataParityService
from services.webull_market_data_service import (
    WebullCredentials,
    WebullMarketDataService,
    _silence_webull_sdk_loggers,
    _suppress_webull_sdk_logging,
    webull_readiness,
)


class FakeQuoteClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def get_latest_quote(self, symbol):
        self.calls.append(symbol)
        return self.payload


class FakeBatchQuoteClient:
    def get_quotes(self, symbols):
        return {
            symbols[0]: {
                "bidPrice": "100.10",
                "askPrice": "100.20",
                "quoteTime": "2026-06-10T10:00:00Z",
            }
        }


class FakeResponse:
    status_code = 200

    def json(self):
        return {
            "bidPrice": "101.10",
            "askPrice": "101.20",
            "quoteTime": "2026-06-10T10:05:00Z",
        }


class FakeNestedMarketData:
    def __init__(self):
        self.calls = []

    def get_quotes(self, symbol, category, depth=1, overnight_required=True):
        self.calls.append((symbol, category, depth, overnight_required))
        return FakeResponse()


class FakeWebullDataClient:
    def __init__(self):
        self.market_data = FakeNestedMarketData()


class FakeProvider:
    def __init__(self, quote):
        self.quote = quote

    def get_latest_quote(self, symbol):
        return self.quote

    def latest_quote_summary(self, symbol):
        return self.quote


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy value, got {value!r}")


def test_webull_readiness_reports_missing_configuration_without_secret_leakage():
    readiness = webull_readiness(
        credentials=WebullCredentials(api_key="", api_secret="", account_id="")
    )

    assert_equal(readiness["configured"], False, "configured")
    assert_equal(readiness["account_id_present"], False, "account id present")
    assert_true(readiness["blockers"], "blockers")
    assert_true("WEBULL_API_KEY" in readiness["blockers"][0], "blocker key name")


def test_webull_quote_client_normalizes_bid_ask_mid_and_spread():
    service = WebullMarketDataService(
        client=FakeQuoteClient(
            {
                "bid_price": "99.90",
                "ask_price": "100.10",
                "timestamp": "2026-06-10T10:00:00Z",
            }
        ),
        credentials=WebullCredentials("key", "secret", "acct"),
    )

    quote = service.latest_quote_summary(" aapl ")

    assert_equal(quote["provider"], "webull", "provider")
    assert_equal(quote["symbol"], "AAPL", "symbol")
    assert_equal(quote["bid"], 99.90, "bid")
    assert_equal(quote["ask"], 100.10, "ask")
    assert_equal(quote["mid"], 100.0, "mid")
    assert_true(quote["spread_pct"] > 0, "spread pct")


def test_webull_quote_client_supports_batch_quote_shape():
    service = WebullMarketDataService(
        client=FakeBatchQuoteClient(),
        credentials=WebullCredentials("key", "secret", "acct"),
    )

    quote = service.latest_quote_summary("MSFT")

    assert_equal(quote["bid"], 100.10, "bid")
    assert_equal(quote["ask"], 100.20, "ask")


def test_webull_quote_client_supports_official_data_client_shape():
    client = FakeWebullDataClient()
    service = WebullMarketDataService(
        client=client,
        credentials=WebullCredentials("key", "secret", "acct"),
    )

    quote = service.latest_quote_summary("MSFT")

    assert_equal(quote["bid"], 101.10, "bid")
    assert_equal(quote["ask"], 101.20, "ask")
    assert_equal(client.market_data.calls, [("MSFT", "US_STOCK", 1, True)], "nested call")


def test_provider_parity_includes_webull_when_service_is_injected():
    parity = MarketDataParityService(
        alpaca_market_data=FakeProvider({"bid": 100.0, "ask": 100.2}),
        polygon_market_data=FakeProvider({"bid": 100.01, "ask": 100.21}),
        webull_market_data=FakeProvider({"bid": 99.99, "ask": 100.19}),
    )

    payload = parity.latest_quote_provider_parity("AAPL")

    assert_equal(payload["status"], "ok", "status")
    assert_equal(payload["providers"]["webull"]["available"], True, "webull available")
    assert_true(payload["mid_range"] is not None, "mid range")


def test_env_credentials_support_app_key_aliases():
    original = {key: os.environ.get(key) for key in os.environ if key.startswith("WEBULL_")}
    try:
        for key in list(os.environ):
            if key.startswith("WEBULL_"):
                os.environ.pop(key)
        os.environ["WEBULL_APP_KEY"] = "app-key"
        os.environ["WEBULL_APP_SECRET"] = "app-secret"
        os.environ["WEBULL_ACCOUNT_ID"] = "account-1"

        service = WebullMarketDataService(client=FakeQuoteClient({}))

        assert_equal(service.credentials.api_key, "app-key", "api key alias")
        assert_equal(service.credentials.api_secret, "app-secret", "secret alias")
        assert_equal(service.credentials.account_id, "account-1", "account")
        assert_equal(service.configured, True, "configured")
    finally:
        for key in list(os.environ):
            if key.startswith("WEBULL_"):
                os.environ.pop(key)
        for key, value in original.items():
            if value is not None:
                os.environ[key] = value


def test_webull_sdk_logger_is_silenced_to_avoid_auth_header_leaks():
    logger = logging.getLogger("webull")
    original = logger.level
    try:
        logger.setLevel(logging.ERROR)
        _silence_webull_sdk_loggers()
        assert_equal(logger.level, logging.CRITICAL, "webull logger level")
    finally:
        logger.setLevel(original)


def test_webull_sdk_logging_suppression_restores_global_logging_state():
    original = logging.root.manager.disable
    with _suppress_webull_sdk_logging():
        assert_equal(logging.root.manager.disable, logging.CRITICAL, "disabled level")

    assert_equal(logging.root.manager.disable, original, "restored disabled level")


def main():
    tests = [
        test_webull_readiness_reports_missing_configuration_without_secret_leakage,
        test_webull_quote_client_normalizes_bid_ask_mid_and_spread,
        test_webull_quote_client_supports_batch_quote_shape,
        test_webull_quote_client_supports_official_data_client_shape,
        test_provider_parity_includes_webull_when_service_is_injected,
        test_env_credentials_support_app_key_aliases,
        test_webull_sdk_logger_is_silenced_to_avoid_auth_header_leaks,
        test_webull_sdk_logging_suppression_restores_global_logging_state,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} Webull market-data service tests passed.")


if __name__ == "__main__":
    main()
