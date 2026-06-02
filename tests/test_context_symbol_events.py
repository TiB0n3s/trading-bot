#!/usr/bin/env python3
"""Tests for context-only event symbols and linked aggregation."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

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
        }
    )
    insert_daily_symbol_event(event, db_path=db_path)

    nvda = aggregate_symbol_events("2026-06-01", "NVDA", db_path=db_path)
    aapl = aggregate_symbol_events("2026-06-01", "AAPL", db_path=db_path)

    assert nvda["has_events"] is True
    assert nvda["event_count"] == 1
    assert nvda["event_context"]["linked_context_event_count"] == 1
    assert nvda["event_context"]["linked_context_symbols"] == ["MU"]
    assert "demand_or_revenue_signal" in nvda["event_context"]["intent_categories"]
    assert aapl["has_events"] is False


def main():
    with tempfile.TemporaryDirectory() as tmp:
        test_context_only_event_aggregates_into_linked_approved_symbol(Path(tmp))
    print("[OK] test_context_only_event_aggregates_into_linked_approved_symbol")
    print("\nAll 1 context symbol event tests passed.")


if __name__ == "__main__":
    main()
