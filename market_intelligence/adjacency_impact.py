"""Value-chain adjacency impact helpers for event intelligence.

This module turns a scored event for one symbol into discounted context for
related approved symbols. It is context-only evidence: no output here has direct
trade authority.
"""

from __future__ import annotations

from typing import Any

try:
    from symbols_config import APPROVED_SYMBOLS, CONTEXT_ONLY_SYMBOL_CONFIG
except ModuleNotFoundError:  # pragma: no cover - package import fallback
    from scripts.symbols_config import APPROVED_SYMBOLS, CONTEXT_ONLY_SYMBOL_CONFIG

ADJACENCY_IMPACT_VERSION = "adjacency_impact_v1"

RELATIONSHIP_WEIGHTS = {
    "direct": 1.0,
    "supplier": 0.6,
    "customer": 0.6,
    "partner": 0.5,
    "competitor": 0.4,
    "peer": 0.4,
    "sector": 0.25,
    "theme": 0.25,
    "unknown": 0.1,
}

RELATIONSHIP_KIND_BY_TYPE = {
    "semiconductor_peer": "peer",
    "semiconductor_equipment_peer": "supplier",
    "semiconductor_ip_peer": "supplier",
    "ai_hardware_peer": "peer",
    "software_peer": "peer",
    "cybersecurity_peer": "peer",
    "consumer_retail_peer": "competitor",
    "pharma_peer": "competitor",
    "biotech_peer": "competitor",
    "spacex_primary_catalyst_placeholder": "sector",
    "space_communications_peer": "peer",
    "space_infrastructure_peer": "peer",
    "space_data_peer": "peer",
    "aerospace_prime_peer": "competitor",
    "ai_compute_power_peer": "supplier",
    "ai_hpc_data_center_peer": "customer",
    "ai_cloud_provider_peer": "customer",
    "advanced_nuclear_power_peer": "supplier",
    "domestic_rare_earth_peer": "supplier",
    "uranium_rare_earth_peer": "supplier",
    "uranium_power_peer": "supplier",
    "autonomous_systems_peer": "peer",
    "aerospace_controls_peer": "supplier",
}

EVENT_RELATIONSHIP_HINTS = {
    "supplier_signal": "supplier",
    "supply_chain": "supplier",
    "customer_contract": "customer",
    "strategic_partnership": "partner",
    "competitive_threat": "competitor",
    "ai_infrastructure_demand": "customer",
}

EXPLICIT_APPROVED_RELATIONSHIPS: dict[str, dict[str, dict[str, Any]]] = {
    "NVDA": {
        "AMD": {"relationship": "competitor", "weight": 0.4, "themes": ["gpu", "ai_infra"]},
        "AVGO": {"relationship": "peer", "weight": 0.4, "themes": ["ai_infra", "semiconductors"]},
        "TSM": {"relationship": "supplier", "weight": 0.6, "themes": ["foundry", "semiconductors"]},
        "ASML": {"relationship": "supplier", "weight": 0.6, "themes": ["equipment"]},
        "VRT": {"relationship": "supplier", "weight": 0.6, "themes": ["data_center_power"]},
        "ETN": {"relationship": "supplier", "weight": 0.6, "themes": ["power_energy"]},
        "CEG": {"relationship": "supplier", "weight": 0.6, "themes": ["power_energy"]},
    },
    "AMD": {
        "NVDA": {"relationship": "competitor", "weight": 0.4, "themes": ["gpu", "ai_infra"]},
        "TSM": {"relationship": "supplier", "weight": 0.6, "themes": ["foundry", "semiconductors"]},
        "ASML": {"relationship": "supplier", "weight": 0.6, "themes": ["equipment"]},
        "AVGO": {"relationship": "peer", "weight": 0.4, "themes": ["ai_infra", "semiconductors"]},
    },
    "TSM": {
        "AAPL": {"relationship": "customer", "weight": 0.6, "themes": ["foundry", "mobile"]},
        "NVDA": {"relationship": "customer", "weight": 0.6, "themes": ["foundry", "gpu"]},
        "AMD": {"relationship": "customer", "weight": 0.6, "themes": ["foundry", "cpu_gpu"]},
        "AVGO": {"relationship": "customer", "weight": 0.6, "themes": ["foundry"]},
        "ASML": {"relationship": "supplier", "weight": 0.6, "themes": ["equipment"]},
    },
    "ASML": {
        "TSM": {"relationship": "customer", "weight": 0.6, "themes": ["equipment"]},
        "NVDA": {"relationship": "supplier", "weight": 0.5, "themes": ["semiconductor_capacity"]},
        "AMD": {"relationship": "supplier", "weight": 0.5, "themes": ["semiconductor_capacity"]},
        "AVGO": {"relationship": "supplier", "weight": 0.5, "themes": ["semiconductor_capacity"]},
    },
    "ORCL": {
        "NVDA": {"relationship": "customer", "weight": 0.6, "themes": ["ai_cloud", "gpu_compute"]},
        "AVGO": {"relationship": "customer", "weight": 0.5, "themes": ["ai_cloud", "networking"]},
        "VRT": {"relationship": "supplier", "weight": 0.6, "themes": ["data_center"]},
        "ETN": {"relationship": "supplier", "weight": 0.5, "themes": ["power_energy"]},
        "CEG": {"relationship": "supplier", "weight": 0.5, "themes": ["power_energy"]},
    },
    "MSFT": {
        "NVDA": {"relationship": "customer", "weight": 0.6, "themes": ["ai_cloud", "gpu_compute"]},
        "AMD": {"relationship": "customer", "weight": 0.4, "themes": ["ai_cloud", "gpu_compute"]},
        "AVGO": {"relationship": "customer", "weight": 0.5, "themes": ["ai_cloud", "networking"]},
    },
    "AMZN": {
        "NVDA": {"relationship": "customer", "weight": 0.5, "themes": ["ai_cloud", "gpu_compute"]},
        "AMD": {"relationship": "customer", "weight": 0.4, "themes": ["ai_cloud", "gpu_compute"]},
        "AVGO": {"relationship": "customer", "weight": 0.5, "themes": ["ai_cloud", "networking"]},
    },
    "GOOGL": {
        "NVDA": {"relationship": "customer", "weight": 0.5, "themes": ["ai_cloud", "gpu_compute"]},
        "AMD": {"relationship": "customer", "weight": 0.4, "themes": ["ai_cloud", "gpu_compute"]},
        "AVGO": {"relationship": "customer", "weight": 0.5, "themes": ["ai_cloud", "networking"]},
    },
    "AVGO": {
        "NVDA": {"relationship": "peer", "weight": 0.4, "themes": ["ai_infra", "semiconductors"]},
        "AMD": {"relationship": "peer", "weight": 0.4, "themes": ["ai_infra", "semiconductors"]},
        "TSM": {"relationship": "supplier", "weight": 0.6, "themes": ["foundry"]},
        "ANET": {"relationship": "competitor", "weight": 0.4, "themes": ["networking"]},
        "MRVL": {"relationship": "competitor", "weight": 0.4, "themes": ["networking"]},
    },
    "ANET": {
        "CSCO": {"relationship": "competitor", "weight": 0.4, "themes": ["networking"]},
        "JNPR": {"relationship": "competitor", "weight": 0.4, "themes": ["networking"]},
        "AVGO": {"relationship": "customer", "weight": 0.4, "themes": ["networking"]},
    },
    "CSCO": {
        "ANET": {"relationship": "competitor", "weight": 0.4, "themes": ["networking"]},
        "JNPR": {"relationship": "competitor", "weight": 0.4, "themes": ["networking"]},
        "AVGO": {"relationship": "customer", "weight": 0.4, "themes": ["networking"]},
    },
    "JNPR": {
        "ANET": {"relationship": "competitor", "weight": 0.4, "themes": ["networking"]},
        "CSCO": {"relationship": "competitor", "weight": 0.4, "themes": ["networking"]},
    },
    "VRT": {
        "ETN": {"relationship": "peer", "weight": 0.4, "themes": ["power_energy", "data_center"]},
        "GEV": {"relationship": "peer", "weight": 0.4, "themes": ["power_energy", "data_center"]},
        "CEG": {"relationship": "supplier", "weight": 0.5, "themes": ["power_energy"]},
        "NVDA": {"relationship": "customer", "weight": 0.5, "themes": ["ai_infra"]},
    },
    "CEG": {
        "VRT": {"relationship": "customer", "weight": 0.4, "themes": ["power_energy"]},
        "ETN": {"relationship": "customer", "weight": 0.4, "themes": ["power_energy"]},
        "GEV": {"relationship": "peer", "weight": 0.4, "themes": ["power_energy"]},
    },
    "MP": {
        "FCX": {"relationship": "peer", "weight": 0.4, "themes": ["critical_materials"]},
        "ALB": {"relationship": "peer", "weight": 0.4, "themes": ["critical_materials"]},
        "KTOS": {"relationship": "supplier", "weight": 0.5, "themes": ["rare_earths", "defense"]},
        "AVAV": {"relationship": "supplier", "weight": 0.5, "themes": ["rare_earths", "defense"]},
    },
    "FCX": {
        "MP": {"relationship": "peer", "weight": 0.4, "themes": ["critical_materials"]},
        "ALB": {"relationship": "peer", "weight": 0.4, "themes": ["critical_materials"]},
        "ETN": {"relationship": "supplier", "weight": 0.4, "themes": ["copper", "power_energy"]},
        "GEV": {"relationship": "supplier", "weight": 0.4, "themes": ["copper", "power_energy"]},
    },
    "ALB": {
        "MP": {"relationship": "peer", "weight": 0.4, "themes": ["critical_materials"]},
        "FCX": {"relationship": "peer", "weight": 0.4, "themes": ["critical_materials"]},
    },
    "RKLB": {
        "KTOS": {"relationship": "peer", "weight": 0.4, "themes": ["space", "defense"]},
        "AVAV": {"relationship": "peer", "weight": 0.4, "themes": ["space", "autonomy"]},
        "NOC": {"relationship": "peer", "weight": 0.35, "themes": ["space", "aerospace"]},
        "LHX": {"relationship": "peer", "weight": 0.35, "themes": ["space", "aerospace"]},
    },
    "KTOS": {
        "RKLB": {"relationship": "peer", "weight": 0.4, "themes": ["space", "defense"]},
        "AVAV": {"relationship": "peer", "weight": 0.4, "themes": ["autonomy", "defense"]},
        "LHX": {"relationship": "peer", "weight": 0.35, "themes": ["defense"]},
    },
    "AVAV": {
        "KTOS": {"relationship": "peer", "weight": 0.4, "themes": ["autonomy", "defense"]},
        "RKLB": {"relationship": "peer", "weight": 0.4, "themes": ["space", "defense"]},
        "LHX": {"relationship": "peer", "weight": 0.35, "themes": ["defense"]},
    },
    "PATH": {
        "SYM": {"relationship": "peer", "weight": 0.35, "themes": ["automation", "robotics"]},
    },
    "SYM": {
        "PATH": {"relationship": "peer", "weight": 0.35, "themes": ["automation", "robotics"]},
    },
}


def _clamp(value: float, low: float = -1.0, high: float = 1.0) -> float:
    return max(low, min(high, float(value)))


def _event_sentiment(event: dict[str, Any]) -> float:
    impact = str(event.get("expected_market_impact") or "neutral")
    if impact == "strongly_bullish":
        base = 1.0
    elif impact == "moderately_bullish":
        base = 0.55
    elif impact == "strongly_bearish":
        base = -1.0
    elif impact == "moderately_bearish":
        base = -0.55
    else:
        return 0.0

    try:
        net = float(event.get("net_event_score"))
    except (TypeError, ValueError):
        return base
    if net:
        base = max(abs(base), min(1.0, abs(net) / 35.0)) * (1 if base > 0 else -1)
    return _clamp(base)


def _source_confidence(event: dict[str, Any]) -> float:
    tier = str(event.get("source_tier") or "unknown")
    if tier == "official":
        return 1.0
    if tier in ("confirmed_financial_news", "deep_analysis"):
        return 0.85
    if tier == "medium_confidence":
        return 0.55
    if tier == "low_confidence":
        return 0.2
    return 0.25


def _symbol_relevance(event: dict[str, Any]) -> float:
    try:
        return max(0.0, min(1.0, float(event.get("symbol_relevance_weight"))))
    except (TypeError, ValueError):
        return 1.0


def relationship_weight(relationship: str | None) -> float:
    relationship = str(relationship or "unknown").lower()
    if relationship in RELATIONSHIP_WEIGHTS:
        return RELATIONSHIP_WEIGHTS[relationship]
    return RELATIONSHIP_WEIGHTS.get(RELATIONSHIP_KIND_BY_TYPE.get(relationship, "unknown"), 0.1)


def relationship_kind(event: dict[str, Any], metadata: dict[str, Any]) -> str:
    explicit = str(metadata.get("relationship") or "").strip().lower()
    if explicit:
        return explicit
    event_type = str(event.get("event_type") or "").strip().lower()
    if event_type in EVENT_RELATIONSHIP_HINTS:
        return EVENT_RELATIONSHIP_HINTS[event_type]
    raw_type = str(event.get("relationship_type") or metadata.get("relationship_type") or "")
    if raw_type:
        return RELATIONSHIP_KIND_BY_TYPE.get(raw_type, "peer")
    return "peer"


def explicit_relationships_for_symbol(symbol: str) -> dict[str, dict[str, Any]]:
    return EXPLICIT_APPROVED_RELATIONSHIPS.get(symbol.upper().strip(), {})


def context_relationships_for_symbol(symbol: str) -> dict[str, dict[str, Any]]:
    cfg = CONTEXT_ONLY_SYMBOL_CONFIG.get(symbol.upper().strip()) or {}
    out: dict[str, dict[str, Any]] = {}
    for target in cfg.get("linked_symbols") or []:
        target_symbol = str(target).upper().strip()
        if target_symbol in APPROVED_SYMBOLS:
            kind = relationship_kind({"relationship_type": cfg.get("relationship_type")}, cfg)
            out[target_symbol] = {
                "relationship": kind,
                "relationship_type": cfg.get("relationship_type"),
                "weight": relationship_weight(kind),
                "themes": cfg.get("themes") or [],
            }
    return out


def related_targets_for_event(event: dict[str, Any]) -> dict[str, dict[str, Any]]:
    symbol = str(event.get("symbol") or "").upper().strip()
    if not symbol:
        return {}
    relationships: dict[str, dict[str, Any]] = {}
    relationships.update(context_relationships_for_symbol(symbol))
    relationships.update(explicit_relationships_for_symbol(symbol))
    relationships.pop(symbol, None)
    return {target: meta for target, meta in relationships.items() if target in APPROVED_SYMBOLS}


def build_adjacency_impacts(event: dict[str, Any]) -> list[dict[str, Any]]:
    sentiment = _event_sentiment(event)
    if sentiment == 0:
        return []

    source_symbol = str(event.get("symbol") or "").upper().strip()
    source_confidence = _source_confidence(event)
    symbol_relevance = _symbol_relevance(event)
    impacts = []

    for target, metadata in sorted(related_targets_for_event(event).items()):
        kind = relationship_kind(event, metadata)
        base_weight = float(metadata.get("weight") or relationship_weight(kind))
        base_weight = max(0.0, min(1.0, base_weight))
        confidence = round(max(0.0, min(1.0, source_confidence * symbol_relevance)), 4)
        impact_score = round(sentiment * base_weight * confidence, 4)
        if impact_score == 0:
            continue
        impacts.append(
            {
                "version": ADJACENCY_IMPACT_VERSION,
                "source_symbol": source_symbol,
                "target_symbol": target,
                "relationship": kind,
                "relationship_type": metadata.get("relationship_type"),
                "relationship_weight": round(base_weight, 4),
                "relationship_themes": metadata.get("themes") or [],
                "source_sentiment": round(sentiment, 4),
                "source_confidence": round(source_confidence, 4),
                "symbol_relevance_weight": round(symbol_relevance, 4),
                "adjacent_impact_score": impact_score,
                "authority": "context_only_no_standalone_trade_authority",
            }
        )
    return impacts


def adjacency_impacts_for_target(event: dict[str, Any], target_symbol: str) -> list[dict[str, Any]]:
    target_symbol = target_symbol.upper().strip()
    return [
        impact
        for impact in event.get("adjacency_impacts") or []
        if str(impact.get("target_symbol") or "").upper() == target_symbol
    ]
