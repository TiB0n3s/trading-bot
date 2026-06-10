"""SpaceX catalyst value-chain graph features.

This module is deterministic metadata and point-in-time feature math only. It
does not grant trading authority. Context-only symbols stay context-only unless
they are explicitly promoted through the approved symbol universe.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable, Sequence

from symbols_config import (
    CONTEXT_ONLY_SYMBOL_CONFIG,
    SPACEX_CATALYST_APPROVED_SYMBOLS_LIST,
    SPACEX_CATALYST_CONTEXT_ONLY_SYMBOLS_LIST,
    SPACEX_CATALYST_SYMBOLS_LIST,
    SYMBOL_CONFIG,
)

SPACEX_VALUE_CHAIN_VERSION = "spacex_value_chain_graph_v1"
SPACEX_VALUE_CHAIN_RUNTIME_EFFECT = "feature_context_only_no_trade_authority"
SPACEX_ANCHOR_SYMBOL = "SPCX"

RELATIONSHIP_BASE_WEIGHTS = {
    "spacex_primary_catalyst_placeholder": 1.0,
    "space_communications_peer": 0.62,
    "space_infrastructure_peer": 0.58,
    "space_data_peer": 0.52,
    "aerospace_prime_peer": 0.68,
}

APPROVED_CATALYST_WEIGHTS = {
    "NOC": 0.74,
    "LHX": 0.72,
    "HON": 0.66,
    "TDY": 0.64,
}


@dataclass(frozen=True)
class ValueChainNode:
    symbol: str
    authority_tier: str
    tradable: bool
    relationship_type: str
    relationship_weight: float
    linked_symbols: list[str]
    themes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValueChainEdge:
    source: str
    target: str
    relationship_type: str
    weight: float
    authority_tier: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class LeadLagShockFeature:
    symbol: str
    anchor_symbol: str
    optimal_lag_steps: int | None
    peak_correlation: float | None
    information_shock_score: float | None
    direction: str
    status: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class ValueChainGraphPayload:
    report_version: str
    runtime_effect: str
    anchor_symbol: str
    nodes: list[ValueChainNode]
    edges: list[ValueChainEdge]
    adjacency_matrix: dict[str, dict[str, float]]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "runtime_effect": self.runtime_effect,
            "anchor_symbol": self.anchor_symbol,
            "nodes": [node.to_dict() for node in self.nodes],
            "edges": [edge.to_dict() for edge in self.edges],
            "adjacency_matrix": self.adjacency_matrix,
            "summary": self.summary,
        }


def _round(value: float | None, digits: int = 6) -> float | None:
    if value is None or not math.isfinite(value):
        return None
    return round(value, digits)


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


def _context_relationship(symbol: str) -> tuple[str, list[str], list[str], float]:
    config = CONTEXT_ONLY_SYMBOL_CONFIG.get(symbol) or {}
    relationship = str(config.get("relationship_type") or "spacex_catalyst_peer")
    linked_symbols = [str(item).upper() for item in config.get("linked_symbols", [])]
    themes = [str(item) for item in config.get("themes", [])]
    weight = RELATIONSHIP_BASE_WEIGHTS.get(relationship, 0.50)
    return relationship, linked_symbols, themes, weight


def _approved_relationship(symbol: str) -> tuple[str, list[str], list[str], float]:
    config = SYMBOL_CONFIG.get(symbol) or {}
    clusters = [str(item) for item in config.get("clusters", [])]
    return (
        "approved_spacex_catalyst_proxy",
        [SPACEX_ANCHOR_SYMBOL],
        clusters,
        APPROVED_CATALYST_WEIGHTS.get(symbol, 0.60),
    )


def build_spacex_value_chain_graph() -> ValueChainGraphPayload:
    nodes: list[ValueChainNode] = []
    edges: list[ValueChainEdge] = []
    matrix: dict[str, dict[str, float]] = {
        symbol: {} for symbol in [SPACEX_ANCHOR_SYMBOL, *SPACEX_CATALYST_SYMBOLS_LIST]
    }

    for symbol in SPACEX_CATALYST_APPROVED_SYMBOLS_LIST:
        relationship, linked_symbols, themes, weight = _approved_relationship(symbol)
        nodes.append(
            ValueChainNode(
                symbol=symbol,
                authority_tier="approved_internal_bar_paper_learning",
                tradable=True,
                relationship_type=relationship,
                relationship_weight=weight,
                linked_symbols=linked_symbols,
                themes=themes,
            )
        )
        edges.append(
            ValueChainEdge(
                source=SPACEX_ANCHOR_SYMBOL,
                target=symbol,
                relationship_type=relationship,
                weight=weight,
                authority_tier="approved_internal_bar_paper_learning",
            )
        )
        matrix[SPACEX_ANCHOR_SYMBOL][symbol] = weight
        matrix[symbol][SPACEX_ANCHOR_SYMBOL] = weight

    for symbol in SPACEX_CATALYST_CONTEXT_ONLY_SYMBOLS_LIST:
        relationship, linked_symbols, themes, weight = _context_relationship(symbol)
        nodes.append(
            ValueChainNode(
                symbol=symbol,
                authority_tier="context_only_no_standalone_buy_authority",
                tradable=False,
                relationship_type=relationship,
                relationship_weight=weight,
                linked_symbols=linked_symbols,
                themes=themes,
            )
        )
        if symbol != SPACEX_ANCHOR_SYMBOL:
            edges.append(
                ValueChainEdge(
                    source=SPACEX_ANCHOR_SYMBOL,
                    target=symbol,
                    relationship_type=relationship,
                    weight=weight,
                    authority_tier="context_only_no_standalone_buy_authority",
                )
            )
            matrix[SPACEX_ANCHOR_SYMBOL][symbol] = weight
            matrix[symbol][SPACEX_ANCHOR_SYMBOL] = weight
        for linked_symbol in linked_symbols:
            if linked_symbol not in SPACEX_CATALYST_APPROVED_SYMBOLS_LIST:
                continue
            secondary_weight = round(weight * 0.85, 6)
            edges.append(
                ValueChainEdge(
                    source=symbol,
                    target=linked_symbol,
                    relationship_type=relationship,
                    weight=secondary_weight,
                    authority_tier="context_enrichment_edge",
                )
            )
            matrix[symbol][linked_symbol] = secondary_weight
            matrix.setdefault(linked_symbol, {})[symbol] = secondary_weight

    return ValueChainGraphPayload(
        report_version=SPACEX_VALUE_CHAIN_VERSION,
        runtime_effect=SPACEX_VALUE_CHAIN_RUNTIME_EFFECT,
        anchor_symbol=SPACEX_ANCHOR_SYMBOL,
        nodes=nodes,
        edges=edges,
        adjacency_matrix={
            symbol: dict(sorted(edges.items())) for symbol, edges in sorted(matrix.items())
        },
        summary={
            "approved_tradable_symbols": list(SPACEX_CATALYST_APPROVED_SYMBOLS_LIST),
            "context_only_symbols": list(SPACEX_CATALYST_CONTEXT_ONLY_SYMBOLS_LIST),
            "node_count": len(nodes),
            "edge_count": len(edges),
            "trade_authority": "approved_symbols_only_normal_risk_gates_still_required",
            "context_only_trade_authority": "never",
        },
    )


def calculate_lead_lag_shock_feature(
    *,
    symbol: str,
    anchor_returns: Sequence[float] | Iterable[float],
    satellite_returns: Sequence[float] | Iterable[float],
    anchor_symbol: str = SPACEX_ANCHOR_SYMBOL,
    max_lag_steps: int = 30,
) -> LeadLagShockFeature:
    anchor = _as_float_sequence(anchor_returns)
    satellite = _as_float_sequence(satellite_returns)
    max_lag = max(0, int(max_lag_steps))
    usable = min(len(anchor), len(satellite))
    if usable < 6:
        return LeadLagShockFeature(
            symbol=symbol.upper(),
            anchor_symbol=anchor_symbol,
            optimal_lag_steps=None,
            peak_correlation=None,
            information_shock_score=None,
            direction="unknown",
            status="insufficient_samples",
        )

    anchor = anchor[-usable:]
    satellite = satellite[-usable:]
    best_lag: int | None = None
    best_corr: float | None = None

    for lag in range(0, min(max_lag, usable - 3) + 1):
        if lag == 0:
            xs = anchor
            ys = satellite
        else:
            xs = anchor[:-lag]
            ys = satellite[lag:]
        corr = _pearson(xs, ys)
        if corr is None:
            continue
        if best_corr is None or abs(corr) > abs(best_corr):
            best_corr = corr
            best_lag = lag

    if best_corr is None or best_lag is None:
        return LeadLagShockFeature(
            symbol=symbol.upper(),
            anchor_symbol=anchor_symbol,
            optimal_lag_steps=None,
            peak_correlation=None,
            information_shock_score=None,
            direction="unknown",
            status="zero_variance",
        )

    shock_score = abs(best_corr) * (1.0 / (1.0 + best_lag / 10.0))
    return LeadLagShockFeature(
        symbol=symbol.upper(),
        anchor_symbol=anchor_symbol,
        optimal_lag_steps=best_lag,
        peak_correlation=_round(best_corr),
        information_shock_score=_round(shock_score),
        direction="positive" if best_corr >= 0 else "negative",
        status="ok",
    )


def build_spacex_value_chain_feature(
    *,
    symbol: str,
    anchor_returns: Sequence[float] | Iterable[float] | None = None,
    satellite_returns: Sequence[float] | Iterable[float] | None = None,
    index_inflow: float | None = None,
    basket_outflow: float | None = None,
) -> dict[str, Any]:
    target = symbol.upper()
    graph = build_spacex_value_chain_graph()
    nodes = {node.symbol: node for node in graph.nodes}
    node = nodes.get(target)
    if node is None:
        return {
            "feature_version": SPACEX_VALUE_CHAIN_VERSION,
            "runtime_effect": SPACEX_VALUE_CHAIN_RUNTIME_EFFECT,
            "symbol": target,
            "in_value_chain": False,
            "authority_tier": "not_in_spacex_value_chain",
        }

    shock = None
    if anchor_returns is not None and satellite_returns is not None:
        shock = calculate_lead_lag_shock_feature(
            symbol=target,
            anchor_returns=anchor_returns,
            satellite_returns=satellite_returns,
        ).to_dict()

    siphon_ratio = None
    if index_inflow is not None and basket_outflow is not None:
        try:
            inflow = float(index_inflow)
            outflow = float(basket_outflow)
            denom = abs(inflow) + abs(outflow)
            siphon_ratio = None if denom <= 0.0 else round(inflow / denom, 6)
        except (TypeError, ValueError):
            siphon_ratio = None

    return {
        "feature_version": SPACEX_VALUE_CHAIN_VERSION,
        "runtime_effect": SPACEX_VALUE_CHAIN_RUNTIME_EFFECT,
        "symbol": target,
        "in_value_chain": True,
        "anchor_symbol": SPACEX_ANCHOR_SYMBOL,
        "authority_tier": node.authority_tier,
        "tradable": node.tradable,
        "relationship_type": node.relationship_type,
        "relationship_weight": node.relationship_weight,
        "themes": node.themes,
        "lead_lag_shock": shock,
        "liquidity_siphon_ratio": siphon_ratio,
    }
