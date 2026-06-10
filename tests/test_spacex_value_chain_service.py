#!/usr/bin/env python3
"""Tests for SpaceX catalyst value-chain graph features."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.spacex_value_chain_service import (  # noqa: E402
    SPACEX_ANCHOR_SYMBOL,
    build_spacex_value_chain_feature,
    build_spacex_value_chain_graph,
    calculate_lead_lag_shock_feature,
)


def test_spacex_value_chain_graph_preserves_authority_tiers():
    payload = build_spacex_value_chain_graph().to_dict()
    nodes = {row["symbol"]: row for row in payload["nodes"]}

    assert payload["report_version"] == "spacex_value_chain_graph_v1"
    assert payload["runtime_effect"] == "feature_context_only_no_trade_authority"
    assert payload["anchor_symbol"] == SPACEX_ANCHOR_SYMBOL
    assert payload["summary"]["approved_tradable_symbols"] == ["NOC", "LHX", "HON", "TDY"]
    assert payload["summary"]["context_only_trade_authority"] == "never"
    assert nodes["NOC"]["tradable"] is True
    assert nodes["NOC"]["authority_tier"] == "approved_internal_bar_paper_learning"
    assert nodes["ASTS"]["tradable"] is False
    assert nodes["ASTS"]["authority_tier"] == "context_only_no_standalone_buy_authority"
    assert payload["adjacency_matrix"]["SPCX"]["NOC"] > payload["adjacency_matrix"]["SPCX"]["SPIR"]


def test_spacex_lead_lag_shock_detects_delayed_satellite_response():
    anchor_returns = [0.01, -0.02, 0.03, 0.04, -0.01, 0.02, 0.01, -0.03, 0.04, 0.02]
    satellite_returns = [0.0, 0.0, *anchor_returns[:-2]]

    feature = calculate_lead_lag_shock_feature(
        symbol="NOC",
        anchor_returns=anchor_returns,
        satellite_returns=satellite_returns,
        max_lag_steps=5,
    ).to_dict()

    assert feature["status"] == "ok"
    assert feature["optimal_lag_steps"] == 2
    assert feature["peak_correlation"] > 0.99
    assert feature["information_shock_score"] > 0.80


def test_spacex_value_chain_feature_blocks_context_only_trade_authority():
    feature = build_spacex_value_chain_feature(
        symbol="ASTS",
        anchor_returns=[0.01, 0.02, 0.03, 0.01, 0.0, -0.01],
        satellite_returns=[0.0, 0.01, 0.02, 0.03, 0.01, 0.0],
        index_inflow=10.0,
        basket_outflow=-5.0,
    )

    assert feature["in_value_chain"] is True
    assert feature["tradable"] is False
    assert feature["authority_tier"] == "context_only_no_standalone_buy_authority"
    assert feature["lead_lag_shock"]["status"] == "ok"
    assert feature["liquidity_siphon_ratio"] == 0.666667


if __name__ == "__main__":
    tests = [
        test_spacex_value_chain_graph_preserves_authority_tiers,
        test_spacex_lead_lag_shock_detects_delayed_satellite_response,
        test_spacex_value_chain_feature_blocks_context_only_trade_authority,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} SpaceX value-chain service tests passed.")
