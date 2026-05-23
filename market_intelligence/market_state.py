#!/usr/bin/env python3
"""
Market state reader.

Read-only helper for loading market_context.json and exposing macro/symbol
context in a consistent shape.

This module does not place orders and does not change live behavior.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parents[1]
MARKET_CONTEXT_PATH = BASE_DIR / "market_context.json"


def load_market_context(path: Path | None = None) -> dict[str, Any]:
    path = path or MARKET_CONTEXT_PATH

    if not path.exists():
        return {
            "market_date": None,
            "macro_regime": "unknown",
            "macro_sentiment": "unknown",
            "macro_summary": "market_context.json missing",
            "symbols": {},
            "source": "missing",
        }

    try:
        data = json.loads(path.read_text())
    except Exception as e:
        return {
            "market_date": None,
            "macro_regime": "error",
            "macro_sentiment": "error",
            "macro_summary": f"failed to parse market_context.json: {e}",
            "symbols": {},
            "source": "parse_error",
        }

    return data if isinstance(data, dict) else {
        "market_date": None,
        "macro_regime": "error",
        "macro_sentiment": "error",
        "macro_summary": "market_context.json did not contain an object",
        "symbols": {},
        "source": "invalid_shape",
    }


def macro_regime(ctx: dict[str, Any]) -> str:
    raw = (
        ctx.get("macro_regime")
        or ctx.get("macro_sentiment")
        or "unknown"
    )
    return str(raw).lower().replace("-", "_").replace(" ", "_")


def symbol_context(symbol: str, ctx: dict[str, Any] | None = None) -> dict[str, Any]:
    ctx = ctx or load_market_context()
    symbols = ctx.get("symbols") or {}
    entry = symbols.get(symbol.upper()) or {}

    if not isinstance(entry, dict):
        entry = {}

    return {
        "symbol": symbol.upper(),
        "bias": entry.get("bias"),
        "reason": entry.get("reason"),
        "confidence": entry.get("confidence"),
        "fundamental_score": entry.get("fundamental_score"),
        "risk_level": entry.get("risk_level"),
        "entry_quality": entry.get("entry_quality"),
        "avoid_type": entry.get("avoid_type"),
    }


def summarize_context(symbol: str) -> dict[str, Any]:
    ctx = load_market_context()
    return {
        "market_date": ctx.get("market_date"),
        "macro_regime": macro_regime(ctx),
        "macro_sentiment": ctx.get("macro_sentiment"),
        "macro_summary": ctx.get("macro_summary"),
        "source": ctx.get("source"),
        "symbol": symbol_context(symbol, ctx),
    }
