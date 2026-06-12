#!/usr/bin/env python3
"""Dealer gamma / options market-maker positioning helpers.

Dealer gamma is structural options context. The bot treats it as volatility
regime, level, and sizing evidence for ML/meta-labeling. It never creates
standalone trade authority.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from market_intelligence.cot_positioning import published_at_is_effective

DEALER_GAMMA_CONTEXT_VERSION = "dealer_gamma_context_v1"
DEALER_GAMMA_STATE_VERSION = "dealer_gamma_state_v1"
DEALER_GAMMA_RUNTIME_EFFECT = "options_dealer_gamma_context_no_trade_authority"

DEFAULT_STATE_PATH = Path("runtime_state/dealer_gamma.json")


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


def option_gex(open_interest: Any, gamma: Any, spot_price: Any, option_type: str) -> float | None:
    """Approximate option gamma exposure for a 1% underlying move."""
    oi = _as_float(open_interest)
    gamma_value = _as_float(gamma)
    spot = _as_float(spot_price)
    if oi is None or gamma_value is None or spot is None or spot <= 0:
        return None
    sign = -1.0 if str(option_type).strip().lower().startswith("p") else 1.0
    return round(oi * gamma_value * spot * spot * 0.01 * sign, 4)


def total_gex(options: list[dict[str, Any]], spot_price: Any) -> float:
    """Sum approximate call and put GEX from normalized option rows."""
    total = 0.0
    for row in options:
        value = row.get("gex")
        if value is None:
            value = option_gex(
                row.get("open_interest"),
                row.get("gamma"),
                spot_price,
                row.get("option_type") or row.get("type") or row.get("right"),
            )
        numeric = _as_float(value)
        if numeric is not None:
            total += numeric
    return round(total, 4)


def gex_regime(total_net_gex: Any) -> str:
    """Classify total net GEX into broad volatility regimes."""
    gex = _as_float(total_net_gex)
    if gex is None:
        return "unknown"
    if gex > 0:
        return "positive_gamma_vol_dampening"
    if gex < 0:
        return "negative_gamma_vol_accelerating"
    return "gamma_neutral"


def gamma_size_modifier(regime: str, distance_to_flip_pct: Any = None) -> float:
    """Return conservative size modifier from dealer gamma regime."""
    distance = _as_float(distance_to_flip_pct)
    if distance is not None and abs(distance) <= 0.5:
        return 0.75
    if regime == "positive_gamma_vol_dampening":
        return 0.85
    if regime == "negative_gamma_vol_accelerating":
        return 1.0
    return 1.0


def nearest_gamma_level(
    spot_price: Any, levels: list[dict[str, Any]], side: str
) -> dict[str, Any] | None:
    """Return nearest heavy positive-gamma level above or below spot."""
    spot = _as_float(spot_price)
    if spot is None:
        return None
    candidates = []
    for level in levels:
        strike = _as_float(level.get("strike"))
        if strike is None:
            continue
        if side == "below" and strike >= spot:
            continue
        if side == "above" and strike <= spot:
            continue
        candidates.append((abs(spot - strike), level))
    if not candidates:
        return None
    return dict(min(candidates, key=lambda item: item[0])[1])


def distance_pct(spot_price: Any, level: Any) -> float | None:
    spot = _as_float(spot_price)
    value = _as_float(level)
    if spot is None or value is None or spot <= 0:
        return None
    return round((spot - value) / spot * 100.0, 4)


def normalize_gamma_levels(levels: list[Any]) -> list[dict[str, Any]]:
    out = []
    for raw in levels:
        if not isinstance(raw, dict):
            continue
        strike = _as_float(raw.get("strike"))
        if strike is None:
            continue
        out.append(
            {
                "strike": _round(strike, 4),
                "net_gex": _round(raw.get("net_gex"), 4),
                "open_interest": _round(raw.get("open_interest"), 4),
                "level_type": raw.get("level_type") or "gamma_peak",
            }
        )
    return sorted(out, key=lambda item: item["strike"])


def normalize_symbol_gamma(symbol: str, payload: dict[str, Any]) -> dict[str, Any]:
    spot = payload.get("spot_price") or payload.get("underlying_price")
    total = payload.get("total_net_gex")
    if total is None:
        total = total_gex(payload.get("options") or [], spot)
    regime = gex_regime(total)
    gamma_flip = payload.get("gamma_flip_zone") or payload.get("gamma_flip_price")
    flip_distance = distance_pct(spot, gamma_flip)
    peak_levels = normalize_gamma_levels(payload.get("absolute_gamma_peak_levels") or [])
    floor = nearest_gamma_level(spot, peak_levels, "below")
    ceiling = nearest_gamma_level(spot, peak_levels, "above")
    published_at = payload.get("published_at") or payload.get("effective_at")

    return {
        "symbol": str(symbol).upper(),
        "source": payload.get("source") or "options_chain_gamma_estimate",
        "as_of_date": payload.get("as_of_date"),
        "published_at": published_at,
        "publication_effective": published_at_is_effective(published_at),
        "spot_price": _round(spot, 4),
        "total_net_gex": _round(total, 4),
        "gex_regime": regime,
        "gamma_flip_zone": _round(gamma_flip, 4),
        "distance_to_gamma_flip_pct": flip_distance,
        "absolute_gamma_peak_levels": peak_levels,
        "nearest_positive_gamma_floor": floor,
        "nearest_positive_gamma_ceiling": ceiling,
        "gamma_size_modifier": gamma_size_modifier(regime, flip_distance),
        "strategy_bias": strategy_bias_for_regime(regime),
        "runtime_effect": DEALER_GAMMA_RUNTIME_EFFECT,
    }


def strategy_bias_for_regime(regime: str) -> str:
    if regime == "positive_gamma_vol_dampening":
        return "mean_reversion_preferred_breakout_size_down"
    if regime == "negative_gamma_vol_accelerating":
        return "momentum_breakout_permitted"
    return "neutral"


def normalize_dealer_gamma_state(raw: dict[str, Any]) -> dict[str, Any]:
    symbols_raw = raw.get("symbols") if isinstance(raw.get("symbols"), dict) else {}
    symbols = {
        str(symbol).upper(): normalize_symbol_gamma(str(symbol), payload or {})
        for symbol, payload in symbols_raw.items()
    }
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "version": DEALER_GAMMA_STATE_VERSION,
        "context_version": DEALER_GAMMA_CONTEXT_VERSION,
        "available": any(
            bool((record or {}).get("publication_effective")) for record in symbols.values()
        ),
        "generated_at": raw.get("generated_at") or generated_at,
        "source": raw.get("source") or "options_chain_gamma_estimate",
        "authority": "options_dealer_gamma_context_only_no_standalone_trade_authority",
        "runtime_effect": DEALER_GAMMA_RUNTIME_EFFECT,
        "symbols": symbols,
    }


def load_dealer_gamma_state(path: Path | str) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {
            "version": DEALER_GAMMA_STATE_VERSION,
            "context_version": DEALER_GAMMA_CONTEXT_VERSION,
            "available": False,
            "reason": f"Dealer gamma state file not found: {path}",
            "runtime_effect": DEALER_GAMMA_RUNTIME_EFFECT,
            "symbols": {},
        }
    try:
        raw = json.loads(path.read_text())
    except Exception as exc:
        return {
            "version": DEALER_GAMMA_STATE_VERSION,
            "context_version": DEALER_GAMMA_CONTEXT_VERSION,
            "available": False,
            "reason": f"Dealer gamma state file parse failed: {exc}",
            "runtime_effect": DEALER_GAMMA_RUNTIME_EFFECT,
            "symbols": {},
        }
    return normalize_dealer_gamma_state(raw)


def dealer_gamma_context_for_symbol(symbol: str, state: dict[str, Any]) -> dict[str, Any] | None:
    records = state.get("symbols") if isinstance(state.get("symbols"), dict) else {}
    payload = records.get(str(symbol or "").upper())
    if not payload or payload.get("publication_effective") is False:
        return None
    out = dict(payload)
    out["authority"] = "options_dealer_gamma_context_only_no_standalone_trade_authority"
    return out
