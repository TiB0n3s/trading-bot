#!/usr/bin/env python3
"""Tests for context-only event symbols and linked aggregation."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from market_intelligence.event_collectors.company_news_collector import (
    event_from_item,  # noqa: E402
)
from market_intelligence.intelligence_store import (  # noqa: E402
    aggregate_symbol_events,
    insert_daily_symbol_event,
)
from market_intelligence.news_event_model import score_event  # noqa: E402


def test_context_only_event_aggregates_into_linked_approved_symbol(tmp_path):
    db_path = tmp_path / "trades.db"
    event = score_event(
        {
            "market_date": "2026-06-01",
            "symbol": "MU",
            "event_type": "industry_demand",
            "event_summary": "Micron reports stronger memory demand from AI infrastructure customers",
            "source": "Reuters",
            "source_tier": "confirmed_financial_news",
            "trusted_source": True,
            "tradable": False,
            "context_only": True,
            "linked_symbols": ["NVDA", "AMD", "TSM"],
            "relationship_type": "semiconductor_peer",
            "relationship_themes": ["semiconductors", "ai_infra", "memory"],
            "ai_event_context": {
                "version": "ai_event_context_v1",
                "provider": "deterministic_fallback",
                "runtime_effect": "context_only_no_live_authority",
                "authority": "context_only_no_standalone_buy_authority",
                "summary": "Memory demand context for linked AI infrastructure symbols.",
                "intent": "demand_or_revenue_signal",
                "affected_symbols": ["NVDA", "AMD", "TSM"],
                "market_alignment": "neutral_context",
                "information_novelty": "new_fundamental_information",
                "positioning_effect": "neutral_positioning_context",
                "earnings_positioning_context": "not_earnings_specific",
                "earnings_information_surprise": "not_earnings_specific",
                "confirmation_status": "reputable_reported",
                "missing_evidence": [],
                "risk_notes": ["context-only"],
            },
        }
    )
    insert_daily_symbol_event(event, db_path=db_path)

    nvda = aggregate_symbol_events("2026-06-01", "NVDA", db_path=db_path)
    aapl = aggregate_symbol_events("2026-06-01", "AAPL", db_path=db_path)

    assert nvda["has_events"] is True
    assert nvda["event_count"] == 1
    assert nvda["event_context"]["linked_context_event_count"] == 1
    assert nvda["event_context"]["linked_context_symbols"] == ["MU"]
    assert nvda["event_context"]["ai_interpretation_count"] == 1
    assert nvda["event_context"]["ai_providers"] == ["deterministic_fallback"]
    assert nvda["event_context"]["ai_market_alignment"] == ["neutral_context"]
    assert nvda["event_context"]["ai_information_novelty"] == ["new_fundamental_information"]
    assert nvda["event_context"]["ai_positioning_effect"] == ["neutral_positioning_context"]
    assert nvda["event_context"]["ai_earnings_positioning_context"] == ["not_earnings_specific"]
    assert nvda["event_context"]["ai_earnings_information_surprise"] == ["not_earnings_specific"]
    assert "demand_or_revenue_signal" in nvda["event_context"]["intent_categories"]
    assert aapl["has_events"] is False


def test_adjacent_context_event_contributes_discounted_impact_to_linked_symbol(tmp_path):
    db_path = tmp_path / "trades.db"
    event = score_event(
        {
            "market_date": "2026-06-01",
            "symbol": "MU",
            "event_type": "industry_demand",
            "event_summary": (
                "Micron reports record AI memory demand growth, beats estimates, "
                "raises forecast, and cites robust expansion"
            ),
            "source": "Reuters",
            "tradable": False,
            "context_only": True,
            "linked_symbols": ["NVDA", "AMD", "TSM"],
            "relationship_type": "semiconductor_peer",
            "relationship_themes": ["semiconductors", "ai_infra", "memory"],
        }
    )
    insert_daily_symbol_event(event, db_path=db_path)

    nvda = aggregate_symbol_events("2026-06-01", "NVDA", db_path=db_path)

    assert event["adjacency_impacts"]
    assert nvda["has_events"] is True
    assert nvda["event_context"]["adjacent_event_count"] == 1
    assert nvda["event_context"]["adjacent_source_symbols"] == ["MU"]
    assert "peer" in nvda["event_context"]["adjacent_relationships"]
    assert nvda["event_context"]["adjacent_impact_score"] > 0
    assert nvda["event_context"]["authority"] == "context_only_no_standalone_buy_authority"


def test_approved_symbol_event_can_create_adjacent_ml_evidence(tmp_path):
    db_path = tmp_path / "trades.db"
    event = score_event(
        {
            "market_date": "2026-06-01",
            "symbol": "TSM",
            "event_type": "guidance",
            "event_summary": (
                "Taiwan Semiconductor raises outlook after record AI foundry demand growth, "
                "beats estimates, and cites robust expansion"
            ),
            "source": "Reuters",
        }
    )
    insert_daily_symbol_event(event, db_path=db_path)

    nvda = aggregate_symbol_events("2026-06-01", "NVDA", db_path=db_path)
    aapl = aggregate_symbol_events("2026-06-01", "AAPL", db_path=db_path)

    assert any(impact["target_symbol"] == "NVDA" for impact in event["adjacency_impacts"])
    assert any(impact["target_symbol"] == "AAPL" for impact in event["adjacency_impacts"])
    assert nvda["event_context"]["adjacent_event_count"] == 1
    assert nvda["event_context"]["adjacent_source_symbols"] == ["TSM"]
    assert "customer" in nvda["event_context"]["adjacent_relationships"]
    assert nvda["event_context"]["adjacent_impact_score"] > 0
    assert aapl["event_context"]["adjacent_impact_score"] > 0


def test_weak_query_match_is_stored_but_downweighted_for_target_symbol(tmp_path):
    db_path = tmp_path / "trades.db"
    collected = event_from_item(
        "2026-06-01",
        "PATH",
        {
            "title": "Should You Buy Nvidia Stock Before June 24? - The Globe and Mail",
            "description": "Nvidia demand and AI infrastructure discussion.",
            "link": "https://example.com/nvidia-context",
            "published_at": "2026-06-01T12:00:00+00:00",
        },
        search_scope="company_direct",
    )
    event = score_event(collected)
    insert_daily_symbol_event(event, db_path=db_path)

    path = aggregate_symbol_events("2026-06-01", "PATH", db_path=db_path)

    assert event["symbol_attribution"] == "weak_query_match"
    assert event["symbol_relevance_weight"] == 0.25
    assert event["expected_market_impact"] == "neutral"
    assert path["has_events"] is True
    assert path["event_context"]["weak_attribution_event_count"] == 1
    assert path["event_context"]["weighted_event_exposure"] == 0.25
    assert path["catalyst_score"] <= 35


def test_ticker_attribution_does_not_match_common_lowercase_word_path():
    event = event_from_item(
        "2026-06-01",
        "PATH",
        {
            "title": "Will SpaceX stock follow the typical path after a skyrocketing IPO? - AOL.com",
            "description": "SpaceX IPO context unrelated to automation software.",
            "link": "https://example.com/spacex-path",
            "published_at": "2026-06-01T12:00:00+00:00",
        },
        search_scope="company_direct",
    )

    assert event["symbol_attribution"] == "weak_query_match"
    assert event["symbol_relevance_weight"] == 0.25


def main():
    with tempfile.TemporaryDirectory() as tmp:
        test_context_only_event_aggregates_into_linked_approved_symbol(Path(tmp))
        test_adjacent_context_event_contributes_discounted_impact_to_linked_symbol(Path(tmp))
        test_approved_symbol_event_can_create_adjacent_ml_evidence(Path(tmp))
        test_weak_query_match_is_stored_but_downweighted_for_target_symbol(Path(tmp))
        test_ticker_attribution_does_not_match_common_lowercase_word_path()
    print("[OK] context symbol event tests passed")


if __name__ == "__main__":
    main()
