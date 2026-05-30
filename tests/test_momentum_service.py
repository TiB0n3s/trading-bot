#!/usr/bin/env python3

from pathlib import Path
from types import SimpleNamespace
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.momentum_service import MomentumService


class FakeMarketData:
    def __init__(self, bars):
        self.bars = bars
        self.calls = []

    def get_bars_with_fallback(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.bars


class FakeLog:
    def warning(self, message):
        self.last_warning = message


def _bar(close, volume=100):
    return SimpleNamespace(c=close, v=volume)


def test_momentum_service_calculates_acceleration_and_volume_surge():
    bars = [
        _bar(100, 100),
        _bar(100.05, 100),
        _bar(100.1, 100),
        _bar(100.15, 100),
        _bar(100.2, 100),
        _bar(100.25, 100),
        _bar(100.3, 100),
        _bar(100.35, 100),
        _bar(100.4, 100),
        _bar(100.45, 100),
        _bar(100.5, 100),
        _bar(100.55, 100),
        _bar(100.6, 100),
        _bar(100.7, 100),
        _bar(101.2, 250),
    ]
    market_data = FakeMarketData(bars)
    service = MomentumService(
        market_data_service=market_data,
        iex_thin_symbols={"AAPL"},
        log=FakeLog(),
    )

    result = service.get_momentum("AAPL", 101.25, premarket_bias="buy")

    assert result["direction"] == "rising"
    assert result["momentum_state"] == "accelerating"
    assert result["volume_state"] == "surge"
    assert result["volume_note"] == "iex_thin"
    assert result["premarket_alignment"] == "confirmed"
    assert market_data.calls[0][0][:2] == ("AAPL", "1Min")
    assert market_data.calls[0][1]["feed"] == "sip"


def test_momentum_service_returns_none_on_insufficient_bars():
    service = MomentumService(
        market_data_service=FakeMarketData([_bar(100)]),
        iex_thin_symbols=set(),
        log=FakeLog(),
    )

    assert service.get_momentum("AAPL", 100.0) is None


def main():
    tests = [
        test_momentum_service_calculates_acceleration_and_volume_surge,
        test_momentum_service_returns_none_on_insufficient_bars,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print("\nAll 2 momentum service tests passed.")


if __name__ == "__main__":
    main()
