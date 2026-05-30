#!/usr/bin/env python3

from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.execution_adapters import ExecutionAdapterService


class FakeMarketData:
    def __init__(self, quotes):
        self.quotes = list(quotes)

    def get_latest_quote(self, symbol):
        quote = self.quotes.pop(0)
        return SimpleNamespace(bid_price=quote[0], ask_price=quote[1])


class FakeLog:
    def warning(self, message):
        self.last_warning = message


def _service(quotes):
    return ExecutionAdapterService(
        market_data_service=FakeMarketData(quotes),
        broker_service=SimpleNamespace(),
        symbol_max_spread_pct={},
        max_bid_ask_spread_pct=0.10,
        max_signal_price_drift_pct=0.35,
        log=FakeLog(),
    )


def test_validate_spread_accepts_tight_quote():
    result = _service([(100.00, 100.05)]).validate_spread_with_retry("AAPL")

    assert result["ok"] is True
    assert result["spread_pct"] < 0.10
    assert result["attempts"] == 1


def test_validate_spread_retries_suspect_quote_then_accepts():
    service = _service([(100.00, 104.00), (100.00, 100.05)])

    result = service.validate_spread_with_retry(
        "AAPL",
        retry_count=2,
        retry_delay_sec=0,
    )

    assert result["ok"] is True
    assert result["attempts"] == 2


def main():
    tests = [
        test_validate_spread_accepts_tight_quote,
        test_validate_spread_retries_suspect_quote_then_accepts,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print("\nAll 2 execution adapter tests passed.")


if __name__ == "__main__":
    main()
