#!/usr/bin/env python3
"""Tests for cross-asset lead-lag mapping."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.cross_asset_lead_lag_service import build_cross_asset_lead_map


def test_cross_asset_lead_map_uses_symbol_clusters_and_default_leads():
    payload = build_cross_asset_lead_map(
        env={},
        symbols=["AAPL", "CVX", "IWM"],
    ).to_dict()
    rows = {row["symbol"]: row for row in payload["rows"]}

    assert payload["runtime_effect"] == "research_mapping_only_no_live_authority"
    assert rows["AAPL"]["lead_tickers"][:3] == ["SPY", "QQQ", "IWM"]
    assert "XLK" in rows["AAPL"]["lead_tickers"]
    assert "XLE" in rows["CVX"]["lead_tickers"]
    assert "IWM" not in rows["IWM"]["lead_tickers"]
    assert payload["summary"]["transformer_authority"] == "not_granted"


def test_cross_asset_lead_map_honors_env_default_leads():
    payload = build_cross_asset_lead_map(
        env={"ETF_LEAD_LAG_REFERENCE_SYMBOLS": "SPY,QQQ,XLK"},
        symbols=["JPM"],
    ).to_dict()

    assert payload["default_leads"] == ["SPY", "QQQ", "XLK"]
    assert "XLF" in payload["rows"][0]["lead_tickers"]


if __name__ == "__main__":
    tests = [
        test_cross_asset_lead_map_uses_symbol_clusters_and_default_leads,
        test_cross_asset_lead_map_honors_env_default_leads,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} cross-asset lead-lag tests passed.")
