#!/usr/bin/env python3
"""Schema tests for rich_market_brief_v1 market_context.json."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

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
    "performance_confidence",
    "performance_evidence",
    "performance_label",
    "performance_reason",
    "performance_score",
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
PLACEHOLDER_TEXT = "Research pending."


def _sample_symbol_entry():
    return {
        "avoid_type": None,
        "bias": "neutral",
        "catalyst_score": 0,
        "confidence": "low",
        "entry_quality": "tactical_only",
        "fundamental_score": "neutral",
        "index_alignment": "mixed",
        "key_catalysts": ["sample catalyst"],
        "key_risks": ["sample risk"],
        "liquidity_quality": "normal",
        "notes": "Sanitized schema-test fixture.",
        "price_location": "near_vwap",
        "performance_confidence": "low",
        "performance_evidence": [],
        "performance_label": "mixed",
        "performance_reason": "Sanitized schema-test fixture.",
        "performance_score": 50,
        "reason": "Sanitized schema-test fixture.",
        "relative_strength_score": 0,
        "resistance_levels": [999999.0],
        "risk_level": "medium",
        "sector_alignment": "mixed",
        "support_levels": [0.01],
        "volume_context": "normal",
    }


def _sample_context():
    return {
        "block_new_buys": False,
        "format": "rich_market_brief_v1",
        "generated_at": "2026-01-01T00:00:00Z",
        "index_state": {
            symbol: {
                "above_vwap": False,
                "key_levels": [],
                "notes": "Sanitized schema-test fixture.",
                "premarket_gap_pct": 0,
                "trend": "neutral",
            }
            for symbol in ("SPY", "QQQ", "IWM", "GLD")
        },
        "macro_events": [],
        "macro_regime": "neutral",
        "macro_sentiment": "neutral",
        "macro_summary": "Sanitized schema-test fixture.",
        "market_date": "2026-01-01",
        "max_new_positions": 8,
        "risk_multiplier": 1.0,
        "sector_state": {
            "technology": {
                "notes": "Sanitized schema-test fixture.",
                "risk": "medium",
                "trend": "neutral",
            }
        },
        "source": "market_brief_builder",
        "symbols": {symbol: _sample_symbol_entry() for symbol in APPROVED_SYMBOLS_LIST},
    }


def load_context(path=None):
    if path is None:
        p = ROOT / "market_context.json"
        if not p.exists():
            return _sample_context()
    else:
        p = Path(path)
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
        for field in ("catalyst_score", "relative_strength_score", "performance_score"):
            value = entry.get(field)
            if not isinstance(value, (int, float)):
                bad[f"{sym}.{field}"] = value

    assert not bad, bad


def test_rich_market_context_symbol_research_lists_are_populated():
    ctx = load_context()
    empty = {}

    for sym, entry in (ctx.get("symbols") or {}).items():
        entry = entry or {}
        for field in (
            "key_catalysts",
            "key_risks",
            "support_levels",
            "resistance_levels",
        ):
            if not entry.get(field):
                empty[f"{sym}.{field}"] = entry.get(field)

    assert not empty, empty


def test_rich_market_context_has_no_research_pending_placeholders():
    ctx = load_context()
    placeholders = []

    def walk(value, path):
        if value == PLACEHOLDER_TEXT:
            placeholders.append(path)
        elif isinstance(value, dict):
            for key, child in value.items():
                walk(child, f"{path}.{key}" if path else str(key))
        elif isinstance(value, list):
            for idx, child in enumerate(value):
                walk(child, f"{path}[{idx}]")

    walk(ctx, "")
    assert not placeholders, placeholders


if __name__ == "__main__":
    test_rich_market_context_has_required_top_fields()
    test_rich_market_context_source_and_format()
    test_rich_market_context_symbol_universe_matches_approved_symbols()
    test_rich_market_context_symbols_have_required_fields()
    test_rich_market_context_index_state_shape()
    test_rich_market_context_sector_state_shape()
    test_rich_market_context_symbol_value_rules()
    test_rich_market_context_score_fields_are_numeric()
    test_rich_market_context_symbol_research_lists_are_populated()
    test_rich_market_context_has_no_research_pending_placeholders()
    print("[OK] rich market context schema")
