#!/usr/bin/env python3
"""Tests for symbol-wide value-chain eco-cluster graph features."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.value_chain_eco_cluster_service import (  # noqa: E402
    build_value_chain_eco_cluster_feature,
    build_value_chain_eco_cluster_graph,
    correlation_relationship_score,
)
from symbols_config import APPROVED_SYMBOLS_LIST, CONTEXT_ONLY_SYMBOLS_LIST  # noqa: E402


def test_value_chain_eco_cluster_graph_covers_all_symbols_without_authority_leak():
    payload = build_value_chain_eco_cluster_graph().to_dict()
    nodes = {row["symbol"]: row for row in payload["nodes"]}

    assert payload["report_version"] == "value_chain_eco_cluster_graph_v1"
    assert payload["runtime_effect"] == "deterministic_feature_context_no_trade_authority"
    assert payload["summary"]["approved_symbol_count"] == len(APPROVED_SYMBOLS_LIST)
    assert payload["summary"]["context_only_symbol_count"] == len(CONTEXT_ONLY_SYMBOLS_LIST)
    assert payload["summary"]["context_only_trade_authority"] == "never"
    assert nodes["AAPL"]["tradable"] is True
    assert nodes["MU"]["tradable"] is False
    assert nodes["MU"]["authority_tier"] == "context_only_no_standalone_buy_authority"
    assert "NVDA" in payload["adjacency_matrix"]["MU"]


def test_value_chain_eco_cluster_feature_scores_peer_and_context_links():
    payload = build_value_chain_eco_cluster_graph()
    nvda = build_value_chain_eco_cluster_feature(symbol="NVDA", graph=payload)
    mu = build_value_chain_eco_cluster_feature(symbol="MU", graph=payload)

    assert nvda["in_eco_cluster"] is True
    assert nvda["tradable"] is True
    assert nvda["graph_degree"] > 0
    assert nvda["max_relationship_weight"] >= 0.62
    assert nvda["linked_context_count"] > 0
    assert mu["tradable"] is False
    assert mu["graph_degree"] > 0


def test_correlation_relationship_score_filters_historical_price_vectors():
    left = [100.0 + i * 0.8 for i in range(40)]
    right = [50.0 + i * 0.4 for i in range(40)]
    weak = [100.0 + ((-1) ** i) * 0.1 for i in range(40)]

    strong = correlation_relationship_score(left, right)
    weak_score = correlation_relationship_score(left, weak)

    assert strong["status"] == "ok"
    assert strong["passes_filter"] is True
    assert strong["correlation"] > 0.99
    assert weak_score["status"] == "ok"
    assert weak_score["passes_filter"] is False


if __name__ == "__main__":
    tests = [
        test_value_chain_eco_cluster_graph_covers_all_symbols_without_authority_leak,
        test_value_chain_eco_cluster_feature_scores_peer_and_context_links,
        test_correlation_relationship_score_filters_historical_price_vectors,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} value-chain eco-cluster service tests passed.")
