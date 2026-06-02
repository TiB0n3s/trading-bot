#!/usr/bin/env python3
"""Tests for portfolio-specific AI toolkit structures."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.portfolio_ai_toolkit_service import (
    earnings_analysis_contract,
    symbol_ai_tool_profile,
    symbol_contagion_watchlist,
    symbol_strategy_archetypes,
)


def test_symbol_ai_tool_profile_maps_semiconductor_contagion_and_tools():
    profile = symbol_ai_tool_profile("ASML")

    assert profile["symbol"] == "ASML"
    assert profile["analytics_tools"]["correlation_cluster_analysis"]["status"] == "active"
    assert profile["analytics_tools"]["alternative_data_matching"]["status"] == "not_primary"
    assert "NVDA" in profile["contagion_watchlist"]
    assert "AMD" in profile["contagion_watchlist"]
    assert profile["external_workflow"]["status"] == "not_configured"
    assert profile["guardrails"]["no_new_trade_authority"] is True


def test_symbol_strategy_archetypes_cover_reversion_and_momentum():
    lin = symbol_strategy_archetypes("LIN")
    crdo = symbol_strategy_archetypes("CRDO")

    assert any(item["name"] == "mean_reversion" for item in lin)
    assert any(item["name"] == "momentum_cascade" for item in crdo)


def test_earnings_analysis_contract_has_required_sections_and_peers():
    contract = earnings_analysis_contract("CRM")

    assert contract["runtime_effect"] == "research_alert_only_no_trade_authority"
    assert contract["required_sections"] == [
        "guidance_nuances",
        "linguistic_hedging",
        "contagion_risk",
        "accounting_inventory_flags",
    ]
    assert "ORCL" in contract["peer_watchlist"]
    assert "VRT" in contract["peer_watchlist"]
    assert contract["score_fields"]["ai_sentiment_score"] == "integer -10..10"


def test_symbol_contagion_watchlist_uses_direct_and_cluster_peers():
    watchlist = symbol_contagion_watchlist("NVDA")

    assert "AMD" in watchlist
    assert "AVGO" in watchlist
    assert "QQQ" in watchlist


def main():
    tests = [
        test_symbol_ai_tool_profile_maps_semiconductor_contagion_and_tools,
        test_symbol_strategy_archetypes_cover_reversion_and_momentum,
        test_earnings_analysis_contract_has_required_sections_and_peers,
        test_symbol_contagion_watchlist_uses_direct_and_cluster_peers,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} portfolio AI toolkit tests passed.")


if __name__ == "__main__":
    main()
