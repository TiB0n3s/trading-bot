#!/usr/bin/env python3
"""Schema tests for market_context-style JSON."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from symbols_config import APPROVED_SYMBOLS_LIST


REQUIRED_TOP = {
    "market_date",
    "macro_sentiment",
    "macro_summary",
    "symbols",
}

REQUIRED_SYMBOL = {
    "bias",
    "reason",
    "confidence",
    "fundamental_score",
    "risk_level",
    "entry_quality",
    "avoid_type",
}


def load_context(path=None):
    p = Path(path) if path else ROOT / "market_context.json"
    return json.loads(p.read_text())


def test_market_context_has_required_top_fields():
    ctx = load_context()
    missing = REQUIRED_TOP - set(ctx.keys())
    assert not missing, f"Missing top-level fields: {sorted(missing)}"


def test_market_context_symbol_universe_matches_approved_symbols():
    ctx = load_context()
    symbols = set((ctx.get("symbols") or {}).keys())
    approved = set(APPROVED_SYMBOLS_LIST)
    assert symbols == approved, {
        "missing": sorted(approved - symbols),
        "extra": sorted(symbols - approved),
    }


def test_market_context_symbols_have_required_fields():
    ctx = load_context()
    bad = {}
    for sym, entry in (ctx.get("symbols") or {}).items():
        missing = REQUIRED_SYMBOL - set((entry or {}).keys())
        if missing:
            bad[sym] = sorted(missing)
    assert not bad, bad


def test_avoid_type_only_set_for_avoid_bias():
    ctx = load_context()
    bad = {}
    for sym, entry in (ctx.get("symbols") or {}).items():
        entry = entry or {}
        if entry.get("bias") != "avoid" and entry.get("avoid_type") is not None:
            bad[sym] = {
                "bias": entry.get("bias"),
                "avoid_type": entry.get("avoid_type"),
            }
    assert not bad, bad


if __name__ == "__main__":
    test_market_context_has_required_top_fields()
    test_market_context_symbol_universe_matches_approved_symbols()
    test_market_context_symbols_have_required_fields()
    test_avoid_type_only_set_for_avoid_bias()
    print("[OK] market context schema")
