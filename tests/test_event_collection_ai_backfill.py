#!/usr/bin/env python3
"""Tests for AI event-context backfill in event collection."""

from __future__ import annotations

import json
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import collect_and_score_events  # noqa: E402
from repositories.market_intelligence_repo import MarketIntelligenceRepository  # noqa: E402


def _insert_event(repo: MarketIntelligenceRepository) -> None:
    now = datetime.now(timezone.utc).isoformat()
    event = {
        "market_date": "2026-06-02",
        "symbol": "AAPL",
        "event_type": "product_launch",
        "event_summary": "Apple announces new product details",
        "source": "Reuters",
        "source_tier": "confirmed_financial_news",
        "source_url": "https://www.reuters.com/example",
        "expected_market_impact": "neutral",
        "trade_relevance": "watch_only",
        "intent_category": "product_catalyst",
        "intent_direction": "neutral_context",
        "confirmation_status": "reported_by_reputable_source",
    }
    repo.insert_daily_symbol_event(
        {
            "market_date": event["market_date"],
            "symbol": event["symbol"],
            "event_type": event["event_type"],
            "event_subtype": None,
            "event_summary": event["event_summary"],
            "source": event["source"],
            "source_url": event["source_url"],
            "product_name": None,
            "company_segment": None,
            "industry": None,
            "expected_market_impact": event["expected_market_impact"],
            "trade_relevance": event["trade_relevance"],
            "time_horizon": "intraday",
            "confidence": "medium",
            "consumer_appetite_score": None,
            "revenue_impact_score": None,
            "profit_potential_score": None,
            "margin_risk_score": None,
            "supply_chain_risk_score": None,
            "materials_risk_score": None,
            "regulatory_risk_score": None,
            "competitive_risk_score": None,
            "execution_risk_score": None,
            "macro_risk_score": None,
            "raw_json": json.dumps(event, sort_keys=True),
            "created_at": now,
            "updated_at": now,
        }
    )


def test_backfill_ai_event_context_updates_existing_raw_json():
    with tempfile.TemporaryDirectory() as tmp:
        repo = MarketIntelligenceRepository(Path(tmp) / "trades.db")
        repo.init_tables()
        _insert_event(repo)

        original_factory = collect_and_score_events.MarketIntelligenceRepository
        collect_and_score_events.MarketIntelligenceRepository = lambda: repo
        try:
            updated, affected = collect_and_score_events.backfill_ai_event_context(
                "2026-06-02",
                provider_name="deterministic",
            )
        finally:
            collect_and_score_events.MarketIntelligenceRepository = original_factory

        assert updated == 1
        assert affected == {"2026-06-02": {"AAPL"}}
        rows = repo.daily_symbol_event_rows_for_date("2026-06-02")
        raw = json.loads(rows[0]["raw_json"])
        assert raw["ai_event_context"]["provider"] == "deterministic_fallback"
        assert raw["ai_event_context"]["runtime_effect"] == "context_only_no_live_authority"


def main():
    tests = [test_backfill_ai_event_context_updates_existing_raw_json]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} event collection AI backfill tests passed.")


if __name__ == "__main__":
    main()
