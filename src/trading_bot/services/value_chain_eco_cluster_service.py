"""Symbol-wide value-chain eco-cluster graph features.

The graph is deterministic and built from checked-in symbol metadata:

- approved symbol cluster membership
- context-only symbol linked_symbols relationships
- relationship categories from context metadata

It is safe for ML training/export because it does not scan external sources,
call brokers, mutate subscriptions, or grant trading authority.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Sequence

from symbols_config import (
    APPROVED_SYMBOLS_LIST,
    CONTEXT_ONLY_SYMBOL_CONFIG,
    CONTEXT_ONLY_SYMBOLS_LIST,
    SYMBOL_CONFIG,
)

VALUE_CHAIN_ECO_CLUSTER_VERSION = "value_chain_eco_cluster_graph_v1"
VALUE_CHAIN_ECO_CLUSTER_RUNTIME_EFFECT = "deterministic_feature_context_no_trade_authority"

CLUSTER_BASE_WEIGHTS = {
    "mega_cap_tech": 0.62,
    "ai_infra": 0.72,
    "semiconductors": 0.70,
    "software_infra": 0.58,
    "hardware_infra": 0.62,
    "cybersecurity": 0.58,
    "consumer": 0.48,
    "consumer_growth": 0.54,
    "energy": 0.62,
    "power_energy": 0.60,
    "industrials": 0.56,
    "aerospace": 0.68,
    "defense": 0.70,
    "healthcare": 0.56,
    "payments": 0.58,
    "financials": 0.54,
    "telecom": 0.50,
    "defensive": 0.46,
    "hedge": 0.42,
    "broad_index": 0.40,
    "spacex_catalyst": 0.74,
}

RELATIONSHIP_BASE_WEIGHTS = {
    "semiconductor_peer": 0.64,
    "semiconductor_equipment_peer": 0.66,
    "ai_hardware_peer": 0.66,
    "semiconductor_ip_peer": 0.60,
    "software_peer": 0.54,
    "cybersecurity_peer": 0.56,
    "consumer_retail_peer": 0.50,
    "pharma_peer": 0.56,
    "biotech_peer": 0.54,
    "spacex_primary_catalyst_placeholder": 1.0,
    "space_communications_peer": 0.62,
    "space_infrastructure_peer": 0.58,
    "space_data_peer": 0.52,
    "aerospace_prime_peer": 0.68,
}


@dataclass(frozen=True)
class EcoClusterNode:
    symbol: str
    authority_tier: str
    tradable: bool
    clusters: list[str]
    themes: list[str]
    relationship_type: str
    linked_symbols: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EcoClusterEdge:
    source: str
    target: str
    relationship_type: str
    weight: float
    evidence: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class EcoClusterGraphPayload:
    report_version: str
    runtime_effect: str
    nodes: list[EcoClusterNode]
    edges: list[EcoClusterEdge]
    adjacency_matrix: dict[str, dict[str, float]]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "runtime_effect": self.runtime_effect,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "adjacency_matrix": self.adjacency_matrix,
            "summary": self.summary,
        }


def _round(value: float | None, digits: int = 6) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


def _approved_clusters(symbol: str) -> list[str]:
    return [str(item) for item in (SYMBOL_CONFIG.get(symbol) or {}).get("clusters", [])]


def _context_config(symbol: str) -> dict[str, Any]:
    return dict(CONTEXT_ONLY_SYMBOL_CONFIG.get(symbol) or {})


def _context_linked_symbols(symbol: str) -> list[str]:
    config = _context_config(symbol)
    return [
        str(item).upper()
        for item in config.get("linked_symbols", [])
        if str(item).upper() in SYMBOL_CONFIG
    ]


def _context_relationship(symbol: str) -> str:
    return str(_context_config(symbol).get("relationship_type") or "context_peer")


def _context_themes(symbol: str) -> list[str]:
    return [str(item) for item in _context_config(symbol).get("themes", [])]


def _edge_key(source: str, target: str) -> tuple[str, str]:
    left, right = sorted((source.upper(), target.upper()))
    return left, right


def _add_edge(
    edges: dict[tuple[str, str], EcoClusterEdge],
    *,
    source: str,
    target: str,
    relationship_type: str,
    weight: float,
    evidence: str,
) -> None:
    if source == target:
        return
    key = _edge_key(source, target)
    existing = edges.get(key)
    rounded_weight = round(max(0.0, min(1.0, weight)), 6)
    if existing is not None and existing.weight >= rounded_weight:
        return
    edges[key] = EcoClusterEdge(
        source=key[0],
        target=key[1],
        relationship_type=relationship_type,
        weight=rounded_weight,
        evidence=evidence,
    )


def build_value_chain_eco_cluster_graph(
    *,
    symbols: Sequence[str] | None = None,
    include_context_symbols: bool = True,
) -> EcoClusterGraphPayload:
    target_symbols = [symbol.upper() for symbol in (symbols or APPROVED_SYMBOLS_LIST)]
    approved_set = set(APPROVED_SYMBOLS_LIST)
    context_set = set(CONTEXT_ONLY_SYMBOLS_LIST) if include_context_symbols else set()
    graph_symbols = sorted((set(target_symbols) & approved_set) | context_set)

    nodes: list[EcoClusterNode] = []
    for symbol in graph_symbols:
        if symbol in approved_set:
            clusters = _approved_clusters(symbol)
            nodes.append(
                EcoClusterNode(
                    symbol=symbol,
                    authority_tier="approved_symbol_normal_risk_gates_required",
                    tradable=True,
                    clusters=clusters,
                    themes=clusters,
                    relationship_type="approved_symbol_cluster_node",
                    linked_symbols=[],
                )
            )
        else:
            nodes.append(
                EcoClusterNode(
                    symbol=symbol,
                    authority_tier="context_only_no_standalone_buy_authority",
                    tradable=False,
                    clusters=[],
                    themes=_context_themes(symbol),
                    relationship_type=_context_relationship(symbol),
                    linked_symbols=_context_linked_symbols(symbol),
                )
            )

    edges: dict[tuple[str, str], EcoClusterEdge] = {}
    approved_targets = [symbol for symbol in graph_symbols if symbol in approved_set]
    for index, source in enumerate(approved_targets):
        source_clusters = set(_approved_clusters(source))
        for target in approved_targets[index + 1 :]:
            shared = sorted(source_clusters & set(_approved_clusters(target)))
            if not shared:
                continue
            weight = max(CLUSTER_BASE_WEIGHTS.get(cluster, 0.45) for cluster in shared)
            if len(shared) > 1:
                weight = min(1.0, weight + 0.04 * (len(shared) - 1))
            _add_edge(
                edges,
                source=source,
                target=target,
                relationship_type="cluster_peer",
                weight=weight,
                evidence="shared_clusters:" + ",".join(shared),
            )

    for context_symbol in sorted(context_set):
        relationship = _context_relationship(context_symbol)
        base_weight = RELATIONSHIP_BASE_WEIGHTS.get(relationship, 0.50)
        for linked_symbol in _context_linked_symbols(context_symbol):
            if linked_symbol not in approved_set:
                continue
            _add_edge(
                edges,
                source=context_symbol,
                target=linked_symbol,
                relationship_type=relationship,
                weight=base_weight,
                evidence="context_only_linked_symbol",
            )

    matrix: dict[str, dict[str, float]] = {symbol: {} for symbol in graph_symbols}
    for edge in edges.values():
        matrix.setdefault(edge.source, {})[edge.target] = edge.weight
        matrix.setdefault(edge.target, {})[edge.source] = edge.weight

    sorted_edges = sorted(edges.values(), key=lambda edge: (edge.source, edge.target))
    return EcoClusterGraphPayload(
        report_version=VALUE_CHAIN_ECO_CLUSTER_VERSION,
        runtime_effect=VALUE_CHAIN_ECO_CLUSTER_RUNTIME_EFFECT,
        nodes=nodes,
        edges=sorted_edges,
        adjacency_matrix={
            symbol: dict(sorted(targets.items())) for symbol, targets in sorted(matrix.items())
        },
        summary={
            "approved_symbol_count": len([node for node in nodes if node.tradable]),
            "context_only_symbol_count": len([node for node in nodes if not node.tradable]),
            "node_count": len(nodes),
            "edge_count": len(sorted_edges),
            "trade_authority": "approved_symbols_only_normal_risk_gates_still_required",
            "context_only_trade_authority": "never",
            "discovery_layer_contract": "external_discovery_must_write_static_metadata_before_premarket_filtering",
        },
    )


def build_value_chain_eco_cluster_feature(
    *,
    symbol: str,
    graph: EcoClusterGraphPayload | None = None,
) -> dict[str, Any]:
    target = symbol.upper()
    payload = graph or build_value_chain_eco_cluster_graph()
    nodes = {node.symbol: node for node in payload.nodes}
    node = nodes.get(target)
    if node is None:
        return {
            "feature_version": VALUE_CHAIN_ECO_CLUSTER_VERSION,
            "runtime_effect": VALUE_CHAIN_ECO_CLUSTER_RUNTIME_EFFECT,
            "symbol": target,
            "in_eco_cluster": False,
            "authority_tier": "not_in_value_chain_eco_cluster",
            "tradable": False,
            "graph_degree": 0,
            "max_relationship_weight": None,
            "avg_relationship_weight": None,
            "linked_context_count": 0,
        }

    neighbors = payload.adjacency_matrix.get(target) or {}
    weights = list(neighbors.values())
    linked_context_count = sum(
        1
        for neighbor in neighbors
        if nodes.get(neighbor) is not None and not nodes[neighbor].tradable
    )
    return {
        "feature_version": VALUE_CHAIN_ECO_CLUSTER_VERSION,
        "runtime_effect": VALUE_CHAIN_ECO_CLUSTER_RUNTIME_EFFECT,
        "symbol": target,
        "in_eco_cluster": True,
        "authority_tier": node.authority_tier,
        "tradable": node.tradable,
        "primary_clusters": node.clusters,
        "themes": node.themes,
        "relationship_type": node.relationship_type,
        "graph_degree": len(neighbors),
        "max_relationship_weight": _round(max(weights) if weights else None),
        "avg_relationship_weight": _round(sum(weights) / len(weights) if weights else None),
        "linked_context_count": linked_context_count,
        "neighbor_symbols": sorted(neighbors),
    }


def _as_float_sequence(values: Sequence[float] | Iterable[float]) -> list[float]:
    result: list[float] = []
    for value in values:
        try:
            item = float(value)
        except (TypeError, ValueError):
            continue
        if math.isfinite(item):
            result.append(item)
    return result


def correlation_relationship_score(
    left_prices: Sequence[float] | Iterable[float],
    right_prices: Sequence[float] | Iterable[float],
) -> dict[str, Any]:
    """Lightweight quantitative filter for pre-market graph validation.

    This intentionally avoids heavyweight optional dependencies. It can be
    replaced by cointegration/ADF tests in a research image, but gives the live
    project a deterministic readiness score from historical price vectors.
    """
    left = _as_float_sequence(left_prices)
    right = _as_float_sequence(right_prices)
    usable = min(len(left), len(right))
    if usable < 20:
        return {"status": "insufficient_samples", "correlation": None, "passes_filter": False}
    left = left[-usable:]
    right = right[-usable:]
    left_returns = [left[i] / left[i - 1] - 1.0 for i in range(1, usable) if left[i - 1] != 0]
    right_returns = [right[i] / right[i - 1] - 1.0 for i in range(1, usable) if right[i - 1] != 0]
    usable_returns = min(len(left_returns), len(right_returns))
    if usable_returns < 20:
        return {"status": "insufficient_returns", "correlation": None, "passes_filter": False}
    left_returns = left_returns[-usable_returns:]
    right_returns = right_returns[-usable_returns:]
    corr = _pearson(left_returns, right_returns)
    if corr is None:
        return {"status": "zero_variance", "correlation": None, "passes_filter": False}
    return {
        "status": "ok",
        "correlation": _round(corr),
        "passes_filter": abs(corr) >= 0.35,
    }


def _pearson(xs: Sequence[float], ys: Sequence[float]) -> float | None:
    if len(xs) != len(ys) or len(xs) < 3:
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    dx = [value - mean_x for value in xs]
    dy = [value - mean_y for value in ys]
    denom_x = math.sqrt(sum(value * value for value in dx))
    denom_y = math.sqrt(sum(value * value for value in dy))
    if denom_x <= 0.0 or denom_y <= 0.0:
        return None
    return sum(left * right for left, right in zip(dx, dy, strict=True)) / (denom_x * denom_y)
