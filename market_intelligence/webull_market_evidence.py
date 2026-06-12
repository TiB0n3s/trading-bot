#!/usr/bin/env python3
"""Webull screener/news/attention context helpers.

This module normalizes Webull non-bar evidence into market_context. The output is
context-only and may be used for learning/attribution, but it never grants
standalone trade authority.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from market_intelligence.cot_positioning import published_at_is_effective

WEBULL_MARKET_CONTEXT_VERSION = "webull_market_context_v1"
WEBULL_MARKET_STATE_VERSION = "webull_market_evidence_state_v1"
WEBULL_MARKET_RUNTIME_EFFECT = "webull_screener_news_attention_context_no_trade_authority"

DEFAULT_STATE_PATH = Path("runtime_state/webull_market_evidence.json")

POSITIVE_NEWS_TONES = {"positive", "bullish", "supportive"}
NEGATIVE_NEWS_TONES = {"negative", "bearish", "caution", "risk"}


def _as_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        text = str(value).strip().replace("%", "").replace(",", "")
        return float(text)
    except (TypeError, ValueError):
        return None


def _as_int(value: Any) -> int | None:
    number = _as_float(value)
    return int(number) if number is not None else None


def _symbol_from_payload(payload: dict[str, Any]) -> str | None:
    for key in ("symbol", "ticker", "instrument", "instrument_symbol", "sec_ticker"):
        value = payload.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip().upper()
    return None


def _payload_list(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, list):
        return [item for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        rows = value.get("rows") or value.get("items") or value.get("data") or value.get("results")
        if isinstance(rows, list):
            return [item for item in rows if isinstance(item, dict)]
    return []


def _normalize_screener_row(
    list_name: str, payload: dict[str, Any], rank: int
) -> dict[str, Any] | None:
    symbol = _symbol_from_payload(payload)
    if not symbol:
        return None
    change_pct = _as_float(
        payload.get("change_pct")
        or payload.get("changeRatio")
        or payload.get("change_ratio")
        or payload.get("pct_change")
    )
    relative_volume_10d = _as_float(
        payload.get("relative_volume_10d")
        or payload.get("relativeVolume10d")
        or payload.get("rel_volume_10d")
    )
    return {
        "symbol": symbol,
        "list": list_name,
        "rank": _as_int(payload.get("rank")) or rank,
        "change_pct": round(change_pct, 4) if change_pct is not None else None,
        "price": _as_float(payload.get("price") or payload.get("last") or payload.get("lastPrice")),
        "volume": _as_int(payload.get("volume")),
        "relative_volume_10d": (
            round(relative_volume_10d, 4) if relative_volume_10d is not None else None
        ),
        "turnover": _as_float(payload.get("turnover")),
        "turnover_rate": _as_float(payload.get("turnover_rate") or payload.get("turnoverRate")),
        "amplitude": _as_float(payload.get("amplitude")),
    }


def _normalize_news_item(payload: dict[str, Any]) -> dict[str, Any] | None:
    symbol = _symbol_from_payload(payload)
    symbols = payload.get("symbols")
    if not symbol and isinstance(symbols, list) and symbols:
        symbol = str(symbols[0]).strip().upper()
    if not symbol:
        return None
    tone = str(payload.get("tone") or payload.get("sentiment") or "neutral").strip().lower()
    title = payload.get("title") or payload.get("headline")
    summary = payload.get("summary") or payload.get("news_summary")
    return {
        "symbol": symbol,
        "tone": tone or "neutral",
        "title": str(title).strip() if title else None,
        "summary": str(summary).strip() if summary else None,
        "source": payload.get("source"),
        "published_at": payload.get("published_at")
        or payload.get("time")
        or payload.get("timestamp"),
        "category": payload.get("category"),
    }


def _normalize_attention_row(payload: dict[str, Any], rank: int) -> dict[str, Any] | None:
    symbol = _symbol_from_payload(payload)
    if not symbol:
        return None
    score = _as_float(payload.get("attention_score") or payload.get("score"))
    return {
        "symbol": symbol,
        "rank": _as_int(payload.get("rank")) or _as_int(payload.get("attention_rank")) or rank,
        "attention_count": _as_int(
            payload.get("attention_count")
            or payload.get("watchlist_count")
            or payload.get("followers")
            or payload.get("follow_count")
        ),
        "attention_score": round(score, 4) if score is not None else None,
        "source": payload.get("source") or "webull_attention",
    }


def _add_symbol(symbols: dict[str, dict[str, Any]], symbol: str) -> dict[str, Any]:
    return symbols.setdefault(
        symbol,
        {
            "symbol": symbol,
            "screener": {"lists": []},
            "news": {"items": []},
            "attention": {},
            "evidence_tags": [],
        },
    )


def _ingest_screener(raw: dict[str, Any], symbols: dict[str, dict[str, Any]]) -> None:
    screeners = raw.get("screeners") or raw.get("screener") or {}
    if not isinstance(screeners, dict):
        return
    for list_name, rows in screeners.items():
        normalized_list = str(list_name).strip().lower().replace(" ", "_")
        for rank, payload in enumerate(_payload_list(rows), start=1):
            row = _normalize_screener_row(normalized_list, payload, rank)
            if not row:
                continue
            entry = _add_symbol(symbols, row["symbol"])
            entry["screener"]["lists"].append(row)
            entry["evidence_tags"].append(f"webull_screener:{normalized_list}:rank={row['rank']}")


def _ingest_news(raw: dict[str, Any], symbols: dict[str, dict[str, Any]]) -> None:
    news = raw.get("news") or raw.get("news_summaries") or {}
    rows: list[dict[str, Any]] = []
    if isinstance(news, dict):
        rows = _payload_list(news.get("items") or news.get("summaries") or news)
        per_symbol = news.get("symbols")
        if isinstance(per_symbol, dict):
            for symbol, payload in per_symbol.items():
                if isinstance(payload, dict):
                    rows.append({"symbol": symbol, **payload})
                elif isinstance(payload, list):
                    rows.extend(
                        {"symbol": symbol, **item} for item in payload if isinstance(item, dict)
                    )
    elif isinstance(news, list):
        rows = [item for item in news if isinstance(item, dict)]

    for payload in rows:
        item = _normalize_news_item(payload)
        if not item:
            continue
        entry = _add_symbol(symbols, item["symbol"])
        entry["news"]["items"].append(item)
        entry["evidence_tags"].append(f"webull_news:{item['tone']}")


def _ingest_attention(raw: dict[str, Any], symbols: dict[str, dict[str, Any]]) -> None:
    attention = raw.get("attention") or raw.get("top_followed") or {}
    rows: list[dict[str, Any]] = []
    if isinstance(attention, dict):
        rows = _payload_list(attention.get("symbols") or attention.get("items") or attention)
        per_symbol = attention.get("symbols")
        if isinstance(per_symbol, dict):
            rows = []
            for symbol, payload in per_symbol.items():
                if isinstance(payload, dict):
                    rows.append({"symbol": symbol, **payload})
    elif isinstance(attention, list):
        rows = [item for item in attention if isinstance(item, dict)]

    for rank, payload in enumerate(rows, start=1):
        row = _normalize_attention_row(payload, rank)
        if not row:
            continue
        entry = _add_symbol(symbols, row["symbol"])
        entry["attention"] = {key: value for key, value in row.items() if key != "symbol"}
        entry["evidence_tags"].append(f"webull_attention:rank={row['rank']}")


def _finalize_symbol_context(symbol: str, payload: dict[str, Any]) -> dict[str, Any]:
    screener_lists = payload.get("screener", {}).get("lists") or []
    news_items = payload.get("news", {}).get("items") or []
    positive_news = sum(1 for item in news_items if item.get("tone") in POSITIVE_NEWS_TONES)
    negative_news = sum(1 for item in news_items if item.get("tone") in NEGATIVE_NEWS_TONES)
    top_active = next((row for row in screener_lists if row.get("list") == "top_active"), None)
    gainer = next(
        (row for row in screener_lists if row.get("list") in {"gainers", "top_gainers"}), None
    )
    loser = next(
        (row for row in screener_lists if row.get("list") in {"losers", "top_losers"}), None
    )
    evidence_tags = sorted(set(payload.get("evidence_tags") or []))

    return {
        "symbol": symbol,
        "context_version": WEBULL_MARKET_CONTEXT_VERSION,
        "runtime_effect": WEBULL_MARKET_RUNTIME_EFFECT,
        "authority": "webull_context_only_no_standalone_trade_authority",
        "screener": {
            "lists": screener_lists[:10],
            "top_active_rank": top_active.get("rank") if top_active else None,
            "gainer_rank": gainer.get("rank") if gainer else None,
            "loser_rank": loser.get("rank") if loser else None,
            "relative_volume_10d": top_active.get("relative_volume_10d") if top_active else None,
        },
        "news": {
            "count": len(news_items),
            "positive_count": positive_news,
            "negative_count": negative_news,
            "items": news_items[:5],
        },
        "attention": payload.get("attention") or {},
        "evidence_tags": evidence_tags,
    }


def normalize_webull_market_evidence_state(raw: dict[str, Any]) -> dict[str, Any]:
    if raw.get("version") == WEBULL_MARKET_STATE_VERSION and isinstance(raw.get("symbols"), dict):
        state = dict(raw)
        published_at = state.get("published_at")
        state["publication_effective"] = published_at_is_effective(published_at)
        state["available"] = bool(state["publication_effective"] and state.get("symbols"))
        if not state["available"]:
            state["reason"] = "Webull market evidence state has no effective context rows"
        else:
            state.pop("reason", None)
        return state

    symbols: dict[str, dict[str, Any]] = {}
    _ingest_screener(raw, symbols)
    _ingest_news(raw, symbols)
    _ingest_attention(raw, symbols)

    finalized = {
        symbol: _finalize_symbol_context(symbol, payload)
        for symbol, payload in sorted(symbols.items())
    }
    published_at = raw.get("published_at") or raw.get("snapshot_at")
    effective = published_at_is_effective(published_at)
    available = bool(effective and finalized)
    state = {
        "version": WEBULL_MARKET_STATE_VERSION,
        "context_version": WEBULL_MARKET_CONTEXT_VERSION,
        "available": available,
        "source": raw.get("source") or "webull_market_evidence_manual",
        "published_at": published_at,
        "publication_effective": effective,
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "runtime_effect": WEBULL_MARKET_RUNTIME_EFFECT,
        "authority": "context_only_no_standalone_trade_authority",
        "symbols": finalized,
        "coverage": {
            "symbol_count": len(finalized),
            "screener_symbol_count": sum(
                1 for payload in finalized.values() if payload.get("screener", {}).get("lists")
            ),
            "news_symbol_count": sum(
                1 for payload in finalized.values() if payload.get("news", {}).get("count")
            ),
            "attention_symbol_count": sum(
                1 for payload in finalized.values() if payload.get("attention")
            ),
        },
    }
    if not available:
        state["reason"] = "Webull market evidence state has no effective context rows"
    return state


def load_webull_market_evidence_state(path: Path | str = DEFAULT_STATE_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {
            "version": WEBULL_MARKET_STATE_VERSION,
            "context_version": WEBULL_MARKET_CONTEXT_VERSION,
            "available": False,
            "reason": f"Webull market evidence state file not found: {path.resolve()}",
            "runtime_effect": WEBULL_MARKET_RUNTIME_EFFECT,
            "symbols": {},
            "coverage": {"symbol_count": 0},
        }
    return normalize_webull_market_evidence_state(json.loads(path.read_text()))


def webull_market_context_for_symbol(symbol: str, state: dict[str, Any]) -> dict[str, Any] | None:
    if not state.get("available"):
        return None
    context = (state.get("symbols") or {}).get(str(symbol or "").upper())
    if not isinstance(context, dict):
        return None
    out = dict(context)
    out["published_at"] = state.get("published_at")
    out["runtime_effect"] = WEBULL_MARKET_RUNTIME_EFFECT
    return out
