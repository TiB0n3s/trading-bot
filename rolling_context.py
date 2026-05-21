#!/usr/bin/env python3
"""
Read-only helpers for rolling_momentum.json.

This module never fetches market data and never places trades.
It only reads the observe-only rolling momentum context written by
rolling_momentum.py.
"""

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
ROLLING_MOMENTUM_FILE = BASE_DIR / "rolling_momentum.json"


def _parse_dt(value: str | None):
    if not value:
        return None
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None


def load_rolling_context(max_age_minutes: int = 30) -> dict[str, Any]:
    """Return rolling momentum context with freshness metadata."""
    result: dict[str, Any] = {
        "available": False,
        "fresh": False,
        "path": str(ROLLING_MOMENTUM_FILE),
        "max_age_minutes": max_age_minutes,
        "age_minutes": None,
        "error": None,
        "data": None,
    }

    if not ROLLING_MOMENTUM_FILE.exists():
        result["error"] = "rolling_momentum.json not found"
        return result

    try:
        data = json.loads(ROLLING_MOMENTUM_FILE.read_text())
    except Exception as e:
        result["error"] = f"failed to parse rolling_momentum.json: {e}"
        return result

    generated_at = _parse_dt(data.get("generated_at"))
    age_minutes = None

    if generated_at:
        if generated_at.tzinfo is None:
            generated_at = generated_at.replace(tzinfo=timezone.utc)
        age_minutes = (datetime.now(timezone.utc) - generated_at.astimezone(timezone.utc)).total_seconds() / 60

    result.update({
        "available": True,
        "fresh": bool(age_minutes is not None and age_minutes <= max_age_minutes),
        "generated_at": data.get("generated_at"),
        "market_time_et": data.get("market_time_et"),
        "symbols_count": data.get("symbols_count"),
        "mode": data.get("mode"),
        "age_minutes": round(age_minutes, 2) if age_minutes is not None else None,
        "data": data,
    })

    return result


def rolling_symbol_context(symbol: str, max_age_minutes: int = 30) -> dict[str, Any] | None:
    ctx = load_rolling_context(max_age_minutes=max_age_minutes)
    data = ctx.get("data") or {}
    symbols = data.get("symbols") or {}
    entry = symbols.get(symbol.upper())

    if not entry:
        return None

    return {
        "fresh": ctx.get("fresh"),
        "age_minutes": ctx.get("age_minutes"),
        "generated_at": ctx.get("generated_at"),
        **entry,
    }


def rolling_summary(max_age_minutes: int = 30) -> dict[str, Any]:
    ctx = load_rolling_context(max_age_minutes=max_age_minutes)
    data = ctx.get("data") or {}
    symbols = data.get("symbols") or {}

    by_context: dict[str, int] = {}
    special_counts: dict[str, int] = {}
    errors = []

    for sym, entry in symbols.items():
        if entry.get("error"):
            errors.append({"symbol": sym, "error": entry.get("error")})

        label = entry.get("trend_context") or "unknown"
        by_context[label] = by_context.get(label, 0) + 1

        for special in entry.get("special_labels") or []:
            special_counts[special] = special_counts.get(special, 0) + 1

    return {
        "available": ctx.get("available"),
        "fresh": ctx.get("fresh"),
        "age_minutes": ctx.get("age_minutes"),
        "generated_at": ctx.get("generated_at"),
        "market_time_et": ctx.get("market_time_et"),
        "symbols_count": len(symbols),
        "by_context": dict(sorted(by_context.items())),
        "special_counts": dict(sorted(special_counts.items())),
        "errors_count": len(errors),
        "errors": errors[:10],
    }
