#!/usr/bin/env python3
"""
Per-position intelligence helper for /positions.

Adds lightweight intelligence context to each open position:
- whether it is weakest holding
- replacement pressure
- strategy memory recommendation
- recent position-manager event
- recent rotation event
"""

import json
from pathlib import Path

from bot_events import fetch_events

BASE_DIR = Path(__file__).resolve().parents[1]

STRATEGY_MEMORY_FILE = BASE_DIR / "strategy_memory.json"
PORTFOLIO_REPLACEMENT_FILE = BASE_DIR / "portfolio_replacement_memory.json"


def _load(path):
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _latest_event(event_type, symbol):
    try:
        rows = fetch_events(limit=1, event_type=event_type, symbol=symbol)
        if not rows:
            return None
        r = rows[0]
        return {
            "timestamp": r["timestamp"],
            "event_type": r["event_type"],
            "action": r["action"],
            "decision": r["decision"],
            "severity": r["severity"],
            "reason": r["reason"],
            "source": r["source"],
        }
    except Exception as e:
        return {"error": str(e)}


def get_position_intelligence(symbol):
    symbol = (symbol or "").upper()

    strategy = _load(STRATEGY_MEMORY_FILE)
    replacement = _load(PORTFOLIO_REPLACEMENT_FILE)

    strategy_symbols = strategy.get("symbols") or {}
    sym_memory = strategy_symbols.get(symbol) or {}

    weakest = replacement.get("weakest_holding") or {}
    strongest = replacement.get("strongest_candidate") or {}

    is_weakest = (weakest.get("symbol") or "").upper() == symbol
    is_strongest_candidate = (strongest.get("symbol") or "").upper() == symbol

    replacement_candidates = replacement.get("replacement_candidates") or []
    candidate_match = None
    for c in replacement_candidates:
        if (c.get("symbol") or "").upper() == symbol:
            candidate_match = c
            break

    return {
        "strategy_memory": {
            "recommendation": sym_memory.get("recommendation"),
            "reason": sym_memory.get("reason"),
            "min_setup_score": sym_memory.get("min_setup_score"),
            "manual_override": sym_memory.get("manual_override"),
            "trades": sym_memory.get("trades"),
            "expectancy": sym_memory.get("expectancy"),
            "win_rate_pct": sym_memory.get("win_rate_pct"),
        },
        "portfolio_replacement": {
            "memory_generated_at": replacement.get("generated_at"),
            "mode": replacement.get("mode"),
            "recommendation": replacement.get("recommendation"),
            "reason": replacement.get("reason"),
            "is_weakest_holding": is_weakest,
            "is_strongest_candidate": is_strongest_candidate,
            "candidate_match": candidate_match,
            "weakest_holding": {
                "symbol": weakest.get("symbol"),
                "unrealized_pl": weakest.get("unrealized_pl"),
                "unrealized_plpc": weakest.get("unrealized_plpc"),
            },
            "strongest_candidate": {
                "symbol": strongest.get("symbol"),
                "score": strongest.get("score"),
                "decision": strongest.get("decision"),
                "buy_opportunity_score": strongest.get("buy_opportunity_score"),
                "buy_opportunity_recommendation": strongest.get("buy_opportunity_recommendation"),
            },
        },
        "recent_events": {
            "position_manager": _latest_event("POSITION_MANAGER", symbol),
            "portfolio_rotation": _latest_event("PORTFOLIO_ROTATION", symbol),
            "portfolio_rotation_order": _latest_event("PORTFOLIO_ROTATION_ORDER", symbol),
        },
    }
