"""
Focused tests for approved symbol universe metadata.

Run:
  python3 tests/test_symbols_config.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from symbols_config import (
    APPROVED_SYMBOLS,
    INTERNAL_BAR_ONLY_SYMBOLS,
    INTERNAL_BAR_ONLY_SYMBOLS_LIST,
    PRICE_RANGES,
    SYMBOL_CONFIG,
    SYMBOL_SIGNAL_SOURCE,
    TRADINGVIEW_ALERT_SYMBOLS,
)


EXPECTED_INTERNAL_ONLY = {
    "AMZN",
    "JPM",
    "TSM",
    "SNPS",
    "DELL",
    "ADSK",
    "NTAP",
    "ZS",
    "PYPL",
    "SOFI",
    "PFE",
    "VZ",
    "T",
    "CMCSA",
    "DKS",
    "MDB",
    "OKTA",
    "BURL",
    "ASML",
}


def test_internal_bar_only_symbols_are_approved_but_not_tradingview():
    assert set(INTERNAL_BAR_ONLY_SYMBOLS_LIST) == EXPECTED_INTERNAL_ONLY
    assert EXPECTED_INTERNAL_ONLY <= APPROVED_SYMBOLS
    assert EXPECTED_INTERNAL_ONLY.isdisjoint(TRADINGVIEW_ALERT_SYMBOLS)


def test_internal_bar_only_symbols_have_ranges_and_source_metadata():
    for symbol in EXPECTED_INTERNAL_ONLY:
        assert symbol in SYMBOL_CONFIG
        low, high = PRICE_RANGES[symbol]
        assert low > 0
        assert high > low
        assert SYMBOL_SIGNAL_SOURCE[symbol] == "internal_bar_only"


def main():
    tests = [
        test_internal_bar_only_symbols_are_approved_but_not_tradingview,
        test_internal_bar_only_symbols_have_ranges_and_source_metadata,
    ]

    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print()
    print(f"All {len(tests)} symbol-config tests passed.")


if __name__ == "__main__":
    main()
