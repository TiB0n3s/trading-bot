#!/usr/bin/env python3

import sys
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from services.rolling_momentum_service import RollingMomentumService


class FakeMarketData:
    def __init__(self, bars):
        self.bars = bars
        self.calls = []

    def get_bars_with_fallback(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.bars


def test_fetch_minute_bars_accepts_current_alpaca_timestamp_shape():
    bars = [
        SimpleNamespace(
            timestamp=datetime(2026, 6, 11, 13, 30, tzinfo=timezone.utc),
            open=100,
            high=101,
            low=99,
            close=100.5,
            volume=1000,
        )
    ]
    service = RollingMomentumService(market_data=FakeMarketData(bars))

    result = service.fetch_minute_bars("AAPL")

    assert result[0]["open"] == 100
    assert result[0]["high"] == 101
    assert result[0]["low"] == 99
    assert result[0]["close"] == 100.5
    assert result[0]["volume"] == 1000
    assert result[0]["ts"].tzinfo is not None


def test_fetch_minute_bars_accepts_legacy_alpaca_bar_shape():
    bars = [
        SimpleNamespace(
            t=datetime(2026, 6, 11, 13, 30, tzinfo=timezone.utc),
            o=100,
            h=101,
            l=99,
            c=100.5,
            v=1000,
        )
    ]
    service = RollingMomentumService(market_data=FakeMarketData(bars))

    result = service.fetch_minute_bars("AAPL")

    assert result[0]["close"] == 100.5
    assert result[0]["volume"] == 1000


def main():
    tests = [
        test_fetch_minute_bars_accepts_current_alpaca_timestamp_shape,
        test_fetch_minute_bars_accepts_legacy_alpaca_bar_shape,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print()
    print(f"All {len(tests)} rolling momentum service tests passed.")


if __name__ == "__main__":
    main()
