#!/usr/bin/env python3
"""Prime brokerage flow and hedge-fund positioning helpers.

Prime brokerage flow data is external institutional positioning context. The
bot treats it as macro/sector/symbol evidence for ML, meta-labeling, and sizing
only. It never creates standalone trade authority.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from market_intelligence.cot_positioning import published_at_is_effective

PB_CONTEXT_VERSION = "prime_brokerage_flow_context_v1"
PB_STATE_VERSION = "prime_brokerage_flow_state_v1"
PB_RUNTIME_EFFECT = "external_prime_brokerage_positioning_context_no_trade_authority"

DEFAULT_STATE_PATH = Path("runtime_state/prime_brokerage_flows.json")

SECTOR_ALIASES = {
    "technology": "information_technology",
    "tech": "information_technology",
    "info_tech": "information_technology",
    "mega_cap_tech": "information_technology",
    "software": "information_technology",
    "software_infra": "information_technology",
    "semiconductors": "information_technology",
    "ai_infra": "information_technology",
    "hardware_infra": "information_technology",
    "networking": "information_technology",
    "automation": "information_technology",
    "robotics": "information_technology",
    "consumer": "consumer_discretionary",
    "consumer_growth": "consumer_discretionary",
    "retail": "consumer_discretionary",
    "healthcare": "healthcare",
    "healthcare_biotech": "healthcare",
    "defense": "industrials",
    "aerospace": "industrials",
    "industrials": "industrials",
    "power_energy": "industrials",
    "energy": "energy",
    "financials": "financials",
    "payments": "financials",
    "telecom": "communication_services",
    "utilities": "utilities",
    "critical_materials": "materials",
    "rare_earths": "materials",
    "copper": "materials",
    "lithium": "materials",
    "hedge": "commodities",
    "broad_index": "broad_market",
}

CLUSTER_SECTOR_PRIORITY = (
    "critical_materials",
    "rare_earths",
    "copper",
    "lithium",
    "semiconductors",
    "ai_infra",
    "software_infra",
    "hardware_infra",
    "networking",
    "mega_cap_tech",
    "defense",
    "aerospace",
    "industrials",
    "power_energy",
    "healthcare",
    "healthcare_biotech",
    "consumer_growth",
    "consumer",
    "payments",
    "financials",
    "energy",
    "telecom",
    "utilities",
    "hedge",
    "broad_index",
)


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


def normalize_sector_name(value: Any) -> str | None:
    if not value:
        return None
    normalized = str(value).strip().lower().replace("-", "_").replace(" ", "_")
    return SECTOR_ALIASES.get(normalized, normalized)


def symbol_to_pb_sector(symbol: str, symbol_config: dict[str, dict[str, Any]]) -> str | None:
    """Map a symbol to a broad PB sector from existing symbol clusters."""
    normalized = str(symbol or "").upper()
    clusters = list((symbol_config.get(normalized) or {}).get("clusters") or [])
    for cluster in CLUSTER_SECTOR_PRIORITY:
        if cluster in clusters:
            return normalize_sector_name(cluster)
    return None


def net_flow_momentum(long_inflows: Any, short_outflows: Any) -> float | None:
    """Return long inflows minus short outflows for the same lookback window."""
    long_value = _as_float(long_inflows)
    short_value = _as_float(short_outflows)
    if long_value is None or short_value is None:
        return None
    return round(long_value - short_value, 4)


def crowding_score(short_exposure: Any, free_float: Any) -> float | None:
    """Return short exposure as a percent of free float."""
    exposure = _as_float(short_exposure)
    float_value = _as_float(free_float)
    if exposure is None or float_value is None or float_value <= 0:
        return None
    return round(exposure / float_value * 100.0, 4)


def is_degrossing(
    long_exposure_change: Any, short_exposure_change: Any, gross_leverage_change: Any
) -> bool:
    """Return True when funds are reducing both books or gross leverage is falling hard."""
    long_change = _as_float(long_exposure_change)
    short_change = _as_float(short_exposure_change)
    gross_change = _as_float(gross_leverage_change)
    if gross_change is not None and gross_change <= -5.0:
        return True
    return bool(
        long_change is not None
        and short_change is not None
        and long_change < 0
        and short_change < 0
    )


def pb_flow_regime(flow_percentile: Any, degrossing: bool, crowded_short: bool) -> str:
    percentile = _as_float(flow_percentile)
    if degrossing:
        return "institutional_degrossing"
    if percentile is not None and percentile <= 10.0:
        return "institutional_distribution_extreme"
    if percentile is not None and percentile <= 25.0:
        return "institutional_distribution"
    if crowded_short:
        return "crowded_short_squeeze_watch"
    if percentile is not None and percentile >= 90.0:
        return "institutional_accumulation_extreme"
    if percentile is not None and percentile >= 75.0:
        return "institutional_accumulation"
    return "neutral"


def pb_size_modifier(regime: str) -> float:
    if regime == "institutional_degrossing":
        return 0.35
    if regime == "institutional_distribution_extreme":
        return 0.5
    if regime == "institutional_distribution":
        return 0.75
    return 1.0


def normalize_flow_record(scope: str, name: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize a sector or symbol PB flow record."""
    flow = payload.get("net_flow_momentum_5d")
    if flow is None:
        flow = net_flow_momentum(payload.get("long_inflows_5d"), payload.get("short_outflows_5d"))

    crowding = payload.get("crowding_score")
    if crowding is None:
        crowding = crowding_score(payload.get("short_exposure"), payload.get("free_float"))

    crowded_short = bool(payload.get("is_crowded_short"))
    crowding_f = _as_float(crowding)
    if crowding_f is not None and crowding_f >= 20.0:
        crowded_short = True

    degrossing = is_degrossing(
        payload.get("long_exposure_change_5d"),
        payload.get("short_exposure_change_5d"),
        payload.get("gross_leverage_change_5d"),
    )
    flow_percentile = payload.get("net_flow_percentile_1y")
    regime = pb_flow_regime(flow_percentile, degrossing, crowded_short)
    published_at = payload.get("published_at") or payload.get("effective_at")

    return {
        "scope": scope,
        "name": name,
        "source": payload.get("source") or "external_prime_brokerage_flow",
        "as_of_date": payload.get("as_of_date"),
        "published_at": published_at,
        "publication_effective": published_at_is_effective(published_at),
        "net_flow_momentum_5d": _round(flow, 4),
        "net_flow_percentile_1y": _round(flow_percentile, 2),
        "gross_leverage": _round(payload.get("gross_leverage"), 4),
        "net_leverage": _round(payload.get("net_leverage"), 4),
        "gross_leverage_change_5d": _round(payload.get("gross_leverage_change_5d"), 4),
        "long_short_ratio": _round(payload.get("long_short_ratio"), 4),
        "long_exposure_change_5d": _round(payload.get("long_exposure_change_5d"), 4),
        "short_exposure_change_5d": _round(payload.get("short_exposure_change_5d"), 4),
        "crowding_score": _round(crowding, 4),
        "is_crowded_short": crowded_short,
        "degrossing_indicator": degrossing,
        "pb_flow_regime": regime,
        "pb_size_modifier": pb_size_modifier(regime),
        "runtime_effect": PB_RUNTIME_EFFECT,
    }


def normalize_prime_brokerage_state(
    raw: dict[str, Any],
    symbol_config: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    sectors_raw = raw.get("sectors") if isinstance(raw.get("sectors"), dict) else {}
    symbols_raw = raw.get("symbols") if isinstance(raw.get("symbols"), dict) else {}
    sectors = {
        normalize_sector_name(sector) or str(sector): normalize_flow_record(
            "sector",
            normalize_sector_name(sector) or str(sector),
            payload or {},
        )
        for sector, payload in sectors_raw.items()
    }
    symbols = {
        str(symbol).upper(): normalize_flow_record("symbol", str(symbol).upper(), payload or {})
        for symbol, payload in symbols_raw.items()
    }
    symbol_sector_map = {
        symbol: sector
        for symbol in sorted(symbol_config)
        if (sector := symbol_to_pb_sector(symbol, symbol_config))
    }
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    return {
        "version": PB_STATE_VERSION,
        "context_version": PB_CONTEXT_VERSION,
        "available": any(
            bool((record or {}).get("publication_effective"))
            for record in [*sectors.values(), *symbols.values()]
        ),
        "generated_at": raw.get("generated_at") or generated_at,
        "source": raw.get("source") or "external_prime_brokerage_flow",
        "authority": "external_positioning_context_size_modifier_only_no_standalone_trade_authority",
        "runtime_effect": PB_RUNTIME_EFFECT,
        "sectors": sectors,
        "symbols": symbols,
        "symbol_sector_map": symbol_sector_map,
    }


def load_prime_brokerage_state(
    path: Path | str,
    symbol_config: dict[str, dict[str, Any]],
) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {
            "version": PB_STATE_VERSION,
            "context_version": PB_CONTEXT_VERSION,
            "available": False,
            "reason": f"Prime brokerage state file not found: {path}",
            "runtime_effect": PB_RUNTIME_EFFECT,
            "sectors": {},
            "symbols": {},
            "symbol_sector_map": {},
        }
    try:
        raw = json.loads(path.read_text())
    except Exception as exc:
        return {
            "version": PB_STATE_VERSION,
            "context_version": PB_CONTEXT_VERSION,
            "available": False,
            "reason": f"Prime brokerage state file parse failed: {exc}",
            "runtime_effect": PB_RUNTIME_EFFECT,
            "sectors": {},
            "symbols": {},
            "symbol_sector_map": {},
        }
    return normalize_prime_brokerage_state(raw, symbol_config)


def prime_brokerage_context_for_symbol(symbol: str, state: dict[str, Any]) -> dict[str, Any] | None:
    """Return symbol-specific PB context, falling back to mapped sector context."""
    normalized = str(symbol or "").upper()
    symbol_records = state.get("symbols") if isinstance(state.get("symbols"), dict) else {}
    if normalized in symbol_records:
        payload = dict(symbol_records[normalized])
        if payload.get("publication_effective") is not False:
            payload["symbol"] = normalized
            payload["mapped_pb_sector"] = payload.get("name")
            payload["authority"] = (
                "external_positioning_context_size_modifier_only_no_standalone_trade_authority"
            )
            return payload

    sectors = state.get("sectors") if isinstance(state.get("sectors"), dict) else {}
    symbol_sector_map = (
        state.get("symbol_sector_map") if isinstance(state.get("symbol_sector_map"), dict) else {}
    )
    sector = symbol_sector_map.get(normalized)
    if not sector or sector not in sectors:
        return None
    payload = dict(sectors[sector])
    if payload.get("publication_effective") is False:
        return None
    payload["symbol"] = normalized
    payload["mapped_pb_sector"] = sector
    payload["authority"] = (
        "external_positioning_context_size_modifier_only_no_standalone_trade_authority"
    )
    return payload
