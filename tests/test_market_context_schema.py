#!/usr/bin/env python3
"""Schema tests for rich_market_brief_v1 market_context.json."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from symbols_config import APPROVED_SYMBOLS_LIST


REQUIRED_TOP = {
    "block_new_buys",
    "format",
    "generated_at",
    "index_state",
    "macro_events",
    "macro_regime",
    "macro_sentiment",
    "macro_summary",
    "market_date",
    "max_new_positions",
    "risk_multiplier",
    "sector_state",
    "source",
    "symbols",
}

REQUIRED_INDEX = {
    "above_vwap",
    "key_levels",
    "notes",
    "premarket_gap_pct",
    "trend",
}

REQUIRED_SECTOR = {
    "notes",
    "risk",
    "trend",
}

REQUIRED_SYMBOL = {
    "avoid_type",
    "bias",
    "catalyst_score",
    "confidence",
    "entry_quality",
    "fundamental_score",
    "index_alignment",
    "key_catalysts",
    "key_risks",
    "liquidity_quality",
    "notes",
    "price_location",
    "reason",
    "relative_strength_score",
    "resistance_levels",
    "risk_level",
    "sector_alignment",
    "support_levels",
    "volume_context",
}

VALID_BIAS = {"buy", "avoid", "neutral"}
VALID_CONFIDENCE = {"high", "medium", "low"}
VALID_AVOID_TYPE = {"hard", "soft", None}


def load_context(path=None):
    p = Path(path) if path else ROOT / "market_context.json"
    return json.loads(p.read_text())


def test_rich_market_context_has_required_top_fields():
    ctx = load_context()
    missing = REQUIRED_TOP - set(ctx.keys())
    assert not missing, f"Missing top-level fields: {sorted(missing)}"


def test_rich_market_context_source_and_format():
    ctx = load_context()
    assert ctx.get("source") == "market_brief_builder"
    assert ctx.get("format") == "rich_market_brief_v1"


def test_rich_market_context_symbol_universe_matches_approved_symbols():
    ctx = load_context()
    symbols = set((ctx.get("symbols") or {}).keys())
    approved = set(APPROVED_SYMBOLS_LIST)
    assert symbols == approved, {
        "missing": sorted(approved - symbols),
        "extra": sorted(symbols - approved),
    }


def test_rich_market_context_symbols_have_required_fields():
    ctx = load_context()
    bad = {}
    for sym, entry in (ctx.get("symbols") or {}).items():
        missing = REQUIRED_SYMBOL - set((entry or {}).keys())
        if missing:
            bad[sym] = sorted(missing)
    assert not bad, bad


def test_rich_market_context_index_state_shape():
    ctx = load_context()
    index_state = ctx.get("index_state") or {}

    required_indexes = {"SPY", "QQQ", "IWM", "GLD"}
    assert required_indexes <= set(index_state.keys()), {
        "missing_indexes": sorted(required_indexes - set(index_state.keys()))
    }

    bad = {}
    for symbol, entry in index_state.items():
        missing = REQUIRED_INDEX - set((entry or {}).keys())
        if missing:
            bad[symbol] = sorted(missing)

        key_levels = (entry or {}).get("key_levels")
        if key_levels is not None:
            assert isinstance(key_levels, list), f"{symbol} key_levels must be list"

    assert not bad, bad


def test_rich_market_context_sector_state_shape():
    ctx = load_context()
    sector_state = ctx.get("sector_state") or {}

    assert isinstance(sector_state, dict)
    assert sector_state, "sector_state must not be empty"

    bad = {}
    for sector, entry in sector_state.items():
        missing = REQUIRED_SECTOR - set((entry or {}).keys())
        if missing:
            bad[sector] = sorted(missing)

    assert not bad, bad


def test_rich_market_context_symbol_value_rules():
    ctx = load_context()
    bad_bias = {}
    bad_confidence = {}
    bad_avoid_type = {}
    bad_lists = {}

    for sym, entry in (ctx.get("symbols") or {}).items():
        entry = entry or {}

        bias = entry.get("bias")
        confidence = entry.get("confidence")
        avoid_type = entry.get("avoid_type")

        if bias not in VALID_BIAS:
            bad_bias[sym] = bias

        if confidence not in VALID_CONFIDENCE:
            bad_confidence[sym] = confidence

        if avoid_type not in VALID_AVOID_TYPE:
            bad_avoid_type[sym] = avoid_type

        if bias != "avoid" and avoid_type is not None:
            bad_avoid_type[sym] = {
                "bias": bias,
                "avoid_type": avoid_type,
                "error": "avoid_type must be null unless bias is avoid",
            }

        for list_field in (
            "key_catalysts",
            "key_risks",
            "support_levels",
            "resistance_levels",
        ):
            if not isinstance(entry.get(list_field), list):
                bad_lists[f"{sym}.{list_field}"] = type(entry.get(list_field)).__name__

    assert not bad_bias, bad_bias
    assert not bad_confidence, bad_confidence
    assert not bad_avoid_type, bad_avoid_type
    assert not bad_lists, bad_lists


def test_rich_market_context_score_fields_are_numeric():
    ctx = load_context()
    bad = {}

    for sym, entry in (ctx.get("symbols") or {}).items():
        entry = entry or {}
        for field in ("catalyst_score", "relative_strength_score"):
            value = entry.get(field)
            if not isinstance(value, (int, float)):
                bad[f"{sym}.{field}"] = value

    assert not bad, bad


if __name__ == "__main__":
    test_rich_market_context_has_required_top_fields()
    test_rich_market_context_source_and_format()
    test_rich_market_context_symbol_universe_matches_approved_symbols()
    test_rich_market_context_symbols_have_required_fields()
    test_rich_market_context_index_state_shape()
    test_rich_market_context_sector_state_shape()
    test_rich_market_context_symbol_value_rules()
    test_rich_market_context_score_fields_are_numeric()
    print("[OK] rich market context schema")
