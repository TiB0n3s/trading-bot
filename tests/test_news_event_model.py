#!/usr/bin/env python3
"""Tests for deterministic news/event scoring semantics."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from market_intelligence.news_event_model import score_event


def test_neutral_headline_baseline_does_not_infer_bullish():
    event = score_event(
        {
            "market_date": "2026-06-01",
            "symbol": "AAPL",
            "event_type": "industry_demand",
            "event_summary": "Apple Inc. stock holdings changed by institutional investor",
            "source": "marketbeat",
            "source_tier": "unclassified",
            "trusted_source": False,
        }
    )

    assert event["expected_market_impact"] == "neutral"
    assert event["trade_relevance"] == "watch_only"
    assert event["net_event_score"] == 0.0


def test_unclassified_source_caps_weak_bullish_inference():
    event = score_event(
        {
            "market_date": "2026-06-01",
            "symbol": "AVGO",
            "event_type": "industry_demand",
            "event_summary": "Broadcom demand growth creates positive AI tailwind",
            "source": "unclassified blog",
            "source_tier": "unclassified",
            "trusted_source": False,
        }
    )

    assert event["expected_market_impact"] == "neutral"
    assert event["trade_relevance"] == "watch_for_confirmation"
    assert "capped by source reliability" in event["scoring_reason"]


def test_trusted_source_can_support_bullish_inference():
    event = score_event(
        {
            "market_date": "2026-06-01",
            "symbol": "AVGO",
            "event_type": "guidance",
            "event_summary": "Broadcom raises outlook after record demand growth and strong margin expansion",
            "source": "reuters",
            "source_tier": "confirmed_financial_news",
            "trusted_source": True,
        }
    )

    assert event["expected_market_impact"] in ("moderately_bullish", "strongly_bullish")
    assert event["trade_relevance"] in ("watch_for_confirmation", "potential_catalyst")
    assert event["net_event_score"] >= 12


def main():
    tests = [
        test_neutral_headline_baseline_does_not_infer_bullish,
        test_unclassified_source_caps_weak_bullish_inference,
        test_trusted_source_can_support_bullish_inference,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} news event model tests passed.")


if __name__ == "__main__":
    main()
