#!/usr/bin/env python3
"""Webull morning brief context helpers.

This is pre-market / morning context only. It may inform ML features, reports,
and size-down/caution logic, but it is not standalone trade authority.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from market_intelligence.cot_positioning import published_at_is_effective

WEBULL_MORNING_BRIEF_CONTEXT_VERSION = "webull_morning_brief_context_v1"
WEBULL_MORNING_BRIEF_STATE_VERSION = "webull_morning_brief_state_v1"
WEBULL_MORNING_BRIEF_RUNTIME_EFFECT = "webull_morning_event_context_no_trade_authority"

DEFAULT_STATE_PATH = Path("runtime_state/webull_morning_brief.json")


def _as_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _normalize_signal_balance(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for horizon, payload in (raw or {}).items():
        if not isinstance(payload, dict):
            continue
        bullish = int(_as_float(payload.get("bullish")) or 0)
        bearish = int(_as_float(payload.get("bearish")) or 0)
        total = bullish + bearish
        out[str(horizon)] = {
            "bullish": bullish,
            "bearish": bearish,
            "net_bullish": bullish - bearish,
            "bullish_share_pct": round(bullish / total * 100.0, 2) if total else None,
        }
    return out


def _normalize_index_futures(raw: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for symbol, payload in (raw or {}).items():
        if isinstance(payload, dict):
            pct = _as_float(payload.get("pct_change") or payload.get("change_pct"))
            value = _as_float(payload.get("value") or payload.get("last"))
        else:
            pct = _as_float(payload)
            value = None
        out[str(symbol).upper()] = {
            "value": value,
            "pct_change": round(pct, 4) if pct is not None else None,
        }
    return out


def _macro_read(index_futures: dict[str, Any], signal_balance: dict[str, Any]) -> str:
    changes = [
        _as_float(payload.get("pct_change"))
        for payload in index_futures.values()
        if isinstance(payload, dict)
    ]
    clean_changes = [value for value in changes if value is not None]
    avg_change = sum(clean_changes) / len(clean_changes) if clean_changes else 0.0
    long_term = signal_balance.get("long_term") or {}
    net_bullish = int(_as_float(long_term.get("net_bullish")) or 0)
    if avg_change <= -0.35 or net_bullish <= -5:
        return "risk_off"
    if avg_change < 0 and net_bullish > 0:
        return "mixed_caution"
    if avg_change >= 0.15 and net_bullish > 0:
        return "mixed_constructive"
    return "mixed_neutral"


def _normalize_symbol_context(symbol: str, payload: dict[str, Any]) -> dict[str, Any]:
    pct_change = _as_float(payload.get("pct_change"))
    context = {
        "symbol": str(symbol).upper(),
        "brief_signal": payload.get("brief_signal") or payload.get("signal"),
        "event_bias": payload.get("event_bias") or payload.get("bias") or "neutral",
        "pct_change": round(pct_change, 4) if pct_change is not None else None,
        "price": _as_float(payload.get("price")),
        "attention_rank": payload.get("attention_rank"),
        "attention_count": payload.get("attention_count"),
        "reason": payload.get("reason"),
        "runtime_effect": WEBULL_MORNING_BRIEF_RUNTIME_EFFECT,
        "authority": "morning_event_context_only_no_standalone_trade_authority",
    }
    return {key: value for key, value in context.items() if value is not None}


def normalize_webull_morning_brief_state(raw: dict[str, Any]) -> dict[str, Any]:
    index_futures = _normalize_index_futures(raw.get("index_futures") or {})
    signal_balance = _normalize_signal_balance(raw.get("technical_signal_balance") or {})
    symbols = {
        str(symbol).upper(): _normalize_symbol_context(str(symbol), payload or {})
        for symbol, payload in (raw.get("symbols") or {}).items()
    }
    published_at = raw.get("published_at") or raw.get("brief_timestamp")
    effective = published_at_is_effective(published_at)
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    state = {
        "version": WEBULL_MORNING_BRIEF_STATE_VERSION,
        "context_version": WEBULL_MORNING_BRIEF_CONTEXT_VERSION,
        "available": bool(effective and (index_futures or signal_balance or symbols)),
        "source": raw.get("source") or "webull_morning_brief_manual",
        "brief_date": raw.get("brief_date"),
        "published_at": published_at,
        "publication_effective": effective,
        "generated_at": generated_at,
        "runtime_effect": WEBULL_MORNING_BRIEF_RUNTIME_EFFECT,
        "macro_read": raw.get("macro_read") or _macro_read(index_futures, signal_balance),
        "index_futures": index_futures,
        "technical_signal_balance": signal_balance,
        "calendar": raw.get("calendar") if isinstance(raw.get("calendar"), dict) else {},
        "news": raw.get("news") if isinstance(raw.get("news"), list) else [],
        "symbols": symbols,
    }
    if not state["available"]:
        state["reason"] = "Webull morning brief state has no effective context rows"
    return state


def load_webull_morning_brief_state(path: Path | str = DEFAULT_STATE_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {
            "version": WEBULL_MORNING_BRIEF_STATE_VERSION,
            "context_version": WEBULL_MORNING_BRIEF_CONTEXT_VERSION,
            "available": False,
            "reason": f"Webull morning brief state file not found: {path.resolve()}",
            "runtime_effect": WEBULL_MORNING_BRIEF_RUNTIME_EFFECT,
            "index_futures": {},
            "technical_signal_balance": {},
            "symbols": {},
        }
    return normalize_webull_morning_brief_state(json.loads(path.read_text()))


def webull_morning_brief_context_for_symbol(
    symbol: str, state: dict[str, Any]
) -> dict[str, Any] | None:
    if not state.get("available"):
        return None
    context = (state.get("symbols") or {}).get(str(symbol or "").upper())
    if not isinstance(context, dict):
        return None
    out = dict(context)
    out["context_version"] = WEBULL_MORNING_BRIEF_CONTEXT_VERSION
    out["brief_date"] = state.get("brief_date")
    out["macro_read"] = state.get("macro_read")
    out["runtime_effect"] = WEBULL_MORNING_BRIEF_RUNTIME_EFFECT
    return out
