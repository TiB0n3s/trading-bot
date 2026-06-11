#!/usr/bin/env python3
"""CFTC Commitments of Traders macro-positioning helpers.

COT is weekly macro context. It is intentionally modeled as a size/risk
modifier and training feature, not as standalone intraday trade authority.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

COT_CONTEXT_VERSION = "cot_positioning_context_v1"
COT_STATE_VERSION = "cot_positioning_state_v1"
COT_RUNTIME_EFFECT = "weekly_macro_positioning_context_no_intraday_trade_authority"

DEFAULT_STATE_PATH = Path("runtime_state/cot_positioning.json")

NASDAQ_CLUSTERS = {
    "mega_cap_tech",
    "semiconductors",
    "ai_infra",
    "software_infra",
    "hardware_infra",
    "networking",
    "automation",
    "robotics",
    "consumer_growth",
}
RUSSELL_CLUSTERS = {"small_cap", "speculative_space"}
GOLD_CLUSTERS = {"hedge"}
SP500_CLUSTERS = {
    "broad_index",
    "industrials",
    "defense",
    "aerospace",
    "healthcare",
    "consumer",
    "payments",
    "financials",
    "telecom",
    "defensive",
    "power_energy",
    "utilities",
    "critical_materials",
}


def _as_float(value: Any) -> float | None:
    try:
        if value is None or isinstance(value, bool):
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _round(value: Any, digits: int = 4) -> float | None:
    numeric = _as_float(value)
    return None if numeric is None else round(numeric, digits)


def published_at_is_effective(published_at: Any, now: datetime | None = None) -> bool:
    """Return False when a COT record has a future publication timestamp."""
    if not published_at:
        return True
    try:
        text = str(published_at).strip().replace("Z", "+00:00")
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
    except ValueError:
        return False
    reference = now or datetime.now(timezone.utc)
    if reference.tzinfo is None:
        reference = reference.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc) <= reference.astimezone(timezone.utc)


def cot_net_position(long_contracts: Any, short_contracts: Any) -> float | None:
    """Return long minus short contracts when both inputs are numeric."""
    long_value = _as_float(long_contracts)
    short_value = _as_float(short_contracts)
    if long_value is None or short_value is None:
        return None
    return long_value - short_value


def cot_index(current_net: Any, net_history: list[Any]) -> float | None:
    """Return the rolling COT percentile index on a 0-100 scale."""
    current = _as_float(current_net)
    history = [_as_float(item) for item in net_history]
    clean_history = [item for item in history if item is not None]
    if current is None or not clean_history:
        return None

    low = min(clean_history)
    high = max(clean_history)
    if high == low:
        return 50.0
    return round((current - low) / (high - low) * 100.0, 2)


def positioning_regime(leveraged_cot_index: Any) -> str:
    """Classify leveraged-fund positioning into actionable macro regimes."""
    index = _as_float(leveraged_cot_index)
    if index is None:
        return "unknown"
    if index >= 95.0:
        return "leveraged_long_extreme"
    if index <= 5.0:
        return "leveraged_short_extreme"
    if index >= 80.0:
        return "leveraged_long_elevated"
    if index <= 20.0:
        return "leveraged_short_elevated"
    return "balanced"


def smart_retail_divergence(
    leveraged_net_change: Any, nonreportable_net_change: Any
) -> float | None:
    """Return aggressive-money net-change minus retail/small-spec net-change."""
    leveraged = _as_float(leveraged_net_change)
    retail = _as_float(nonreportable_net_change)
    if leveraged is None or retail is None:
        return None
    return round(leveraged - retail, 4)


def size_modifier_for_regime(regime: str, open_interest_change: Any = None) -> float:
    """Return conservative COT context size modifier.

    The modifier is a macro overlay only. Existing live risk, execution-quality,
    affordability, and authority gates remain superior.
    """
    oi_change = _as_float(open_interest_change)
    if regime in {"leveraged_long_extreme", "leveraged_short_extreme"}:
        return 0.5
    if regime in {"leveraged_long_elevated", "leveraged_short_elevated"}:
        return 0.75
    if regime == "balanced" and oi_change is not None and oi_change > 0:
        return 1.0
    return 1.0


def symbol_to_cot_market(symbol: str, symbol_config: dict[str, dict[str, Any]]) -> str | None:
    """Map an equity/ETF symbol to the broad COT futures market proxy."""
    normalized = str(symbol or "").upper()
    if normalized == "QQQ":
        return "NASDAQ_100"
    if normalized == "SPY":
        return "S_AND_P_500"
    if normalized == "IWM":
        return "RUSSELL_2000"
    if normalized == "GLD":
        return "GOLD"

    clusters = set((symbol_config.get(normalized) or {}).get("clusters") or [])
    if clusters & GOLD_CLUSTERS:
        return "GOLD"
    if clusters & RUSSELL_CLUSTERS:
        return "RUSSELL_2000"
    if clusters & NASDAQ_CLUSTERS:
        return "NASDAQ_100"
    if clusters & SP500_CLUSTERS:
        return "S_AND_P_500"
    return None


def normalize_market_record(market: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize one COT market record from raw or already-derived values."""
    leveraged_net = payload.get("leveraged_funds_net")
    if leveraged_net is None:
        leveraged_net = cot_net_position(
            payload.get("leveraged_funds_long"),
            payload.get("leveraged_funds_short"),
        )

    asset_manager_net = payload.get("asset_manager_net")
    if asset_manager_net is None:
        asset_manager_net = cot_net_position(
            payload.get("asset_manager_long"),
            payload.get("asset_manager_short"),
        )

    dealer_net = payload.get("dealer_intermediary_net")
    if dealer_net is None:
        dealer_net = cot_net_position(
            payload.get("dealer_intermediary_long"),
            payload.get("dealer_intermediary_short"),
        )

    nonreportable_net = payload.get("nonreportable_net")
    if nonreportable_net is None:
        nonreportable_net = cot_net_position(
            payload.get("nonreportable_long"),
            payload.get("nonreportable_short"),
        )

    leveraged_index = payload.get("leveraged_funds_cot_index_52w")
    if leveraged_index is None:
        leveraged_index = cot_index(leveraged_net, payload.get("leveraged_funds_net_history") or [])

    regime = positioning_regime(leveraged_index)
    divergence = payload.get("smart_retail_divergence")
    if divergence is None:
        divergence = smart_retail_divergence(
            payload.get("leveraged_funds_net_change"),
            payload.get("nonreportable_net_change"),
        )

    open_interest_change = payload.get("open_interest_change")

    published_at = payload.get("published_at")
    return {
        "market": market,
        "source": payload.get("source") or "cftc_cot_financial_futures",
        "as_of_date": payload.get("as_of_date"),
        "published_at": published_at,
        "publication_effective": published_at_is_effective(published_at),
        "dealer_intermediary_net": _round(dealer_net, 2),
        "asset_manager_net": _round(asset_manager_net, 2),
        "leveraged_funds_net": _round(leveraged_net, 2),
        "leveraged_funds_net_change": _round(payload.get("leveraged_funds_net_change"), 2),
        "leveraged_funds_cot_index_52w": _round(leveraged_index, 2),
        "nonreportable_net": _round(nonreportable_net, 2),
        "nonreportable_net_change": _round(payload.get("nonreportable_net_change"), 2),
        "smart_retail_divergence": _round(divergence, 2),
        "open_interest": _round(payload.get("open_interest"), 2),
        "open_interest_change": _round(open_interest_change, 2),
        "positioning_regime": regime,
        "cot_size_modifier": size_modifier_for_regime(regime, open_interest_change),
        "runtime_effect": COT_RUNTIME_EFFECT,
    }


def normalize_cot_state(
    raw: dict[str, Any],
    symbol_config: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    """Normalize a full COT state payload and add symbol mapping."""
    markets_raw = raw.get("markets") if isinstance(raw.get("markets"), dict) else {}
    markets = {
        str(market): normalize_market_record(str(market), payload or {})
        for market, payload in markets_raw.items()
    }
    symbol_map = {
        symbol: market
        for symbol in sorted(symbol_config)
        if (market := symbol_to_cot_market(symbol, symbol_config))
    }
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "version": COT_STATE_VERSION,
        "context_version": COT_CONTEXT_VERSION,
        "available": any(
            bool((market or {}).get("publication_effective")) for market in markets.values()
        ),
        "generated_at": raw.get("generated_at") or generated_at,
        "source": raw.get("source") or "cftc_cot_financial_futures",
        "authority": "macro_context_size_modifier_only_no_standalone_trade_authority",
        "runtime_effect": COT_RUNTIME_EFFECT,
        "markets": markets,
        "symbol_map": symbol_map,
    }


def load_cot_state(path: Path | str, symbol_config: dict[str, dict[str, Any]]) -> dict[str, Any]:
    """Load and normalize COT state from disk. Missing files return an empty state."""
    path = Path(path)
    if not path.exists():
        return {
            "version": COT_STATE_VERSION,
            "context_version": COT_CONTEXT_VERSION,
            "available": False,
            "reason": f"COT state file not found: {path}",
            "runtime_effect": COT_RUNTIME_EFFECT,
            "markets": {},
            "symbol_map": {},
        }
    try:
        raw = json.loads(path.read_text())
    except Exception as exc:
        return {
            "version": COT_STATE_VERSION,
            "context_version": COT_CONTEXT_VERSION,
            "available": False,
            "reason": f"COT state file parse failed: {exc}",
            "runtime_effect": COT_RUNTIME_EFFECT,
            "markets": {},
            "symbol_map": {},
        }
    state = normalize_cot_state(raw, symbol_config)
    return state


def cot_context_for_symbol(symbol: str, state: dict[str, Any]) -> dict[str, Any] | None:
    """Return the COT context payload for one symbol, if mapped and available."""
    markets = state.get("markets") if isinstance(state.get("markets"), dict) else {}
    symbol_map = state.get("symbol_map") if isinstance(state.get("symbol_map"), dict) else {}
    market = symbol_map.get(str(symbol or "").upper())
    if not market or market not in markets:
        return None
    payload = dict(markets[market])
    if payload.get("publication_effective") is False:
        return None
    payload["symbol"] = str(symbol or "").upper()
    payload["mapped_cot_market"] = market
    payload["authority"] = "macro_context_size_modifier_only_no_standalone_trade_authority"
    return payload
