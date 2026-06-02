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
    assert event["event_intent"]["intent_direction"] == "neutral_context"
    assert event["event_intent"]["authority"] == "context_only_no_standalone_buy_authority"


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


def test_supplier_signal_models_risk_without_untrusted_bullish_jump():
    event = score_event(
        {
            "market_date": "2026-06-01",
            "symbol": "NVDA",
            "event_type": "supplier_signal",
            "event_summary": "Key supplier warns of component shortage and delayed factory output",
            "source": "industry blog",
            "source_tier": "unclassified",
            "trusted_source": False,
        }
    )

    assert event["expected_market_impact"] in ("neutral", "moderately_bearish")
    assert event["supply_chain_risk_score"] > 40
    assert event["execution_risk_score"] > 35
    assert event["intent_category"] == "supply_chain_or_input_risk"
    assert event["intent_scope"] == "peripheral_company"
    assert "direct_company_confirmation" in event["missing_evidence"]


def test_untrusted_deal_chatter_requires_confirmation():
    event = score_event(
        {
            "market_date": "2026-06-01",
            "symbol": "CRM",
            "event_type": "mna_deal_chatter",
            "event_summary": "Salesforce in backdoor deal talks for acquisition after strong growth reports",
            "source": "message board",
            "source_tier": "low_confidence",
            "trusted_source": False,
        }
    )

    assert event["expected_market_impact"] == "neutral"
    assert event["trade_relevance"] in ("watch_only", "watch_for_confirmation")
    assert "rumor-sensitive peripheral event requires trusted confirmation" in event["scoring_reason"]
    assert event["confirmation_status"] == "unconfirmed"
    assert "official_or_second_reputable_source" in event["missing_evidence"]


def test_leadership_departure_is_execution_risk_not_bullish():
    event = score_event(
        {
            "market_date": "2026-06-01",
            "symbol": "AAPL",
            "event_type": "leadership_personnel",
            "event_summary": "Apple CFO resigns as company names interim finance chief",
            "source": "reuters",
            "source_tier": "confirmed_financial_news",
            "trusted_source": True,
        }
    )

    assert event["expected_market_impact"] in ("neutral", "moderately_bearish")
    assert event["execution_risk_score"] > 40
    assert event["intent_category"] == "management_execution_signal"


def main():
    tests = [
        test_neutral_headline_baseline_does_not_infer_bullish,
        test_unclassified_source_caps_weak_bullish_inference,
        test_trusted_source_can_support_bullish_inference,
        test_supplier_signal_models_risk_without_untrusted_bullish_jump,
        test_untrusted_deal_chatter_requires_confirmation,
        test_leadership_departure_is_execution_risk_not_bullish,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} news event model tests passed.")


if __name__ == "__main__":
    main()
