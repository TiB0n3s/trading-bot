"""
Focused tests for approved symbol universe metadata.

Run:
  python3 tests/test_symbols_config.py
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from symbols_config import (
    APPROVED_SYMBOLS,
    CONTEXT_ONLY_SYMBOL_CONFIG,
    CONTEXT_ONLY_SYMBOLS,
    EVENT_CONTEXT_SYMBOLS,
    INTERNAL_BAR_ONLY_SYMBOLS,
    INTERNAL_BAR_ONLY_SYMBOLS_LIST,
    PRICE_RANGES,
    SPACEX_CATALYST_APPROVED_SYMBOLS,
    SPACEX_CATALYST_APPROVED_SYMBOLS_LIST,
    SPACEX_CATALYST_CONTEXT_ONLY_SYMBOLS,
    SPACEX_CATALYST_CONTEXT_ONLY_SYMBOLS_LIST,
    SPACEX_CATALYST_SYMBOLS,
    SPACEX_CATALYST_SYMBOLS_LIST,
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
    "NOC",
    "LHX",
    "HON",
    "TDY",
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


def test_context_only_symbols_are_non_tradable_and_link_to_approved_symbols():
    assert CONTEXT_ONLY_SYMBOLS
    assert CONTEXT_ONLY_SYMBOLS.isdisjoint(APPROVED_SYMBOLS)
    assert EVENT_CONTEXT_SYMBOLS == APPROVED_SYMBOLS | CONTEXT_ONLY_SYMBOLS

    for symbol, cfg in CONTEXT_ONLY_SYMBOL_CONFIG.items():
        assert symbol in CONTEXT_ONLY_SYMBOLS
        assert cfg.get("name")
        assert cfg.get("relationship_type")
        linked = set(cfg.get("linked_symbols") or [])
        assert linked
        assert linked <= APPROVED_SYMBOLS


def test_spacex_catalyst_universe_has_explicit_authority_tiers():
    assert SPACEX_CATALYST_APPROVED_SYMBOLS_LIST == ["NOC", "LHX", "HON", "TDY"]
    assert SPACEX_CATALYST_APPROVED_SYMBOLS <= APPROVED_SYMBOLS
    assert SPACEX_CATALYST_APPROVED_SYMBOLS <= INTERNAL_BAR_ONLY_SYMBOLS
    assert SPACEX_CATALYST_APPROVED_SYMBOLS.isdisjoint(TRADINGVIEW_ALERT_SYMBOLS)

    expected_context = {"SPCX", "IRDM", "ASTS", "GSAT", "RDW", "PL", "BKSY", "SPIR", "BA"}
    assert set(SPACEX_CATALYST_CONTEXT_ONLY_SYMBOLS_LIST) == expected_context
    assert SPACEX_CATALYST_CONTEXT_ONLY_SYMBOLS == expected_context
    assert SPACEX_CATALYST_CONTEXT_ONLY_SYMBOLS <= CONTEXT_ONLY_SYMBOLS
    assert SPACEX_CATALYST_CONTEXT_ONLY_SYMBOLS.isdisjoint(APPROVED_SYMBOLS)

    assert set(SPACEX_CATALYST_SYMBOLS_LIST) == (
        SPACEX_CATALYST_APPROVED_SYMBOLS | SPACEX_CATALYST_CONTEXT_ONLY_SYMBOLS
    )
    assert SPACEX_CATALYST_SYMBOLS == (
        SPACEX_CATALYST_APPROVED_SYMBOLS | SPACEX_CATALYST_CONTEXT_ONLY_SYMBOLS
    )

    for symbol in SPACEX_CATALYST_CONTEXT_ONLY_SYMBOLS:
        cfg = CONTEXT_ONLY_SYMBOL_CONFIG[symbol]
        assert "authority_note" in cfg
        assert "context_only" in cfg["authority_note"]


def main():
    tests = [
        test_internal_bar_only_symbols_are_approved_but_not_tradingview,
        test_internal_bar_only_symbols_have_ranges_and_source_metadata,
        test_context_only_symbols_are_non_tradable_and_link_to_approved_symbols,
        test_spacex_catalyst_universe_has_explicit_authority_tiers,
    ]

    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print()
    print(f"All {len(tests)} symbol-config tests passed.")


if __name__ == "__main__":
    main()
