#!/usr/bin/env python3
"""
Market brief builder.

Builds a normalized, richer market_context.json structure from raw research data.

This is read-only/helper logic. It does not place orders, approve trades,
reject trades, or change live behavior.
"""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytz
from symbols_config import APPROVED_SYMBOLS

from market_intelligence.market_brief_schema import (
    normalize_market_context,
    schema_quality_summary,
)

ET = pytz.timezone("America/New_York")


def now_et_iso() -> str:
    return datetime.now(ET).isoformat()


def default_index_state() -> dict[str, dict[str, Any]]:
    """Return default index-state placeholders."""
    return {
        "SPY": {
            "trend": "mixed",
            "premarket_gap_pct": None,
            "above_vwap": None,
            "key_levels": [],
            "notes": "Default placeholder; replace with researched index context.",
        },
        "QQQ": {
            "trend": "mixed",
            "premarket_gap_pct": None,
            "above_vwap": None,
            "key_levels": [],
            "notes": "Default placeholder; replace with researched index context.",
        },
        "IWM": {
            "trend": "mixed",
            "premarket_gap_pct": None,
            "above_vwap": None,
            "key_levels": [],
            "notes": "Default placeholder; replace with researched index context.",
        },
        "GLD": {
            "trend": "mixed",
            "premarket_gap_pct": None,
            "above_vwap": None,
            "key_levels": [],
            "notes": "Default placeholder; replace with researched hedge/gold context.",
        },
    }


def default_sector_state() -> dict[str, dict[str, Any]]:
    """Return default sector/theme-state placeholders."""
    return {
        "mega_cap_tech": {
            "trend": "mixed",
            "risk": "medium",
            "notes": "Default placeholder.",
        },
        "semiconductors": {
            "trend": "mixed",
            "risk": "medium",
            "notes": "Default placeholder.",
        },
        "energy": {
            "trend": "mixed",
            "risk": "medium",
            "notes": "Default placeholder.",
        },
        "industrials": {
            "trend": "mixed",
            "risk": "medium",
            "notes": "Default placeholder.",
        },
        "defense": {
            "trend": "mixed",
            "risk": "medium",
            "notes": "Default placeholder.",
        },
        "healthcare_biotech": {
            "trend": "mixed",
            "risk": "medium",
            "notes": "Default placeholder.",
        },
        "consumer_retail": {
            "trend": "mixed",
            "risk": "medium",
            "notes": "Default placeholder.",
        },
        "payments": {
            "trend": "mixed",
            "risk": "medium",
            "notes": "Default placeholder.",
        },
    }


def default_symbol_entry(symbol: str) -> dict[str, Any]:
    """Return conservative default symbol research."""
    return {
        "bias": "neutral",
        "reason": "No symbol-specific research provided; defaulting to neutral.",
        "confidence": "low",
        "fundamental_score": "neutral",
        "risk_level": "medium",
        "entry_quality": "conditional",
        "avoid_type": None,
        "catalyst_score": 3,
        "relative_strength_score": 5,
        "sector_alignment": "mixed",
        "index_alignment": "mixed",
        "liquidity_quality": "acceptable",
        "volume_context": "normal",
        "price_location": "range_bound",
        "key_catalysts": [],
        "key_risks": ["insufficient automated research detail"],
        "support_levels": [],
        "resistance_levels": [],
        "notes": "Auto-filled conservative default.",
    }


def merge_symbol_research(raw_symbols: dict[str, Any] | None) -> dict[str, Any]:
    """
    Merge raw symbol research onto conservative defaults for all approved symbols.
    """
    raw_symbols = raw_symbols or {}
    merged = {}

    for symbol in sorted(APPROVED_SYMBOLS):
        base = default_symbol_entry(symbol)
        raw = raw_symbols.get(symbol) or {}

        if isinstance(raw, dict):
            base.update(raw)

        merged[symbol] = base

    return merged


def build_market_brief(
    raw: dict[str, Any] | None = None,
    market_date: str | None = None,
    source: str = "market_brief_builder",
) -> dict[str, Any]:
    """
    Build a normalized richer market context from raw research data.

    raw may contain:
      - macro_sentiment
      - macro_regime
      - macro_summary
      - risk_multiplier
      - max_new_positions
      - block_new_buys
      - index_state
      - sector_state
      - macro_events
      - symbols
    """
    raw = raw or {}
    today = datetime.now(ET).date().isoformat()

    assembled = {
        "market_date": market_date or raw.get("market_date") or today,
        "generated_at": raw.get("generated_at") or now_et_iso(),
        "macro_sentiment": raw.get("macro_sentiment") or "mixed",
        "macro_regime": raw.get("macro_regime") or "caution",
        "macro_summary": raw.get("macro_summary")
        or "Auto-built default market brief; replace with full research.",
        "risk_multiplier": raw.get("risk_multiplier", 0.75),
        "max_new_positions": raw.get("max_new_positions", 6),
        "block_new_buys": raw.get("block_new_buys", False),
        "index_state": raw.get("index_state")
        if isinstance(raw.get("index_state"), dict)
        else default_index_state(),
        "sector_state": raw.get("sector_state")
        if isinstance(raw.get("sector_state"), dict)
        else default_sector_state(),
        "macro_events": raw.get("macro_events")
        if isinstance(raw.get("macro_events"), list)
        else [],
        "data_only": raw.get("data_only"),
        "source_quality": raw.get("source_quality"),
        "event_enrichment_count": raw.get("event_enrichment_count"),
        "intraday_refresh_at": raw.get("intraday_refresh_at"),
        "cot_positioning_context": raw.get("cot_positioning_context"),
        "prime_brokerage_context": raw.get("prime_brokerage_context"),
        "dealer_gamma_context": raw.get("dealer_gamma_context"),
        "webull_morning_brief_context": raw.get("webull_morning_brief_context"),
        "symbols": merge_symbol_research(raw.get("symbols")),
        "source": source,
        "format": "rich_market_brief_v1",
    }

    return normalize_market_context(assembled, APPROVED_SYMBOLS)


def write_market_context(
    brief: dict[str, Any],
    path: Path | str = "market_context.json",
) -> None:
    path = Path(path)
    path.write_text(json.dumps(brief, indent=2, sort_keys=True) + "\n")


def load_raw_research(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    return json.loads(path.read_text())


def build_from_file(
    input_path: Path | str,
    output_path: Path | str = "market_context.json",
    market_date: str | None = None,
) -> dict[str, Any]:
    raw = load_raw_research(input_path)
    brief = build_market_brief(
        raw,
        market_date=market_date,
        source=f"market_brief_builder:{Path(input_path).name}",
    )
    write_market_context(brief, output_path)
    return brief


def summary_for_brief(brief: dict[str, Any]) -> dict[str, Any]:
    return schema_quality_summary(brief)
