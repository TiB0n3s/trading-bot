#!/usr/bin/env python3
"""Tests for context-only AI event interpretation."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.ai_event_context_service import (  # noqa: E402
    AI_EVENT_CONTEXT_AUTHORITY,
    AIEventContextConfig,
    AIEventContextService,
    deterministic_event_context,
)


def _event():
    return {
        "symbol": "MU",
        "event_type": "industry_demand",
        "event_summary": "Micron reports stronger memory demand from AI infrastructure customers",
        "source_tier": "confirmed_financial_news",
        "context_only": True,
        "linked_symbols": ["NVDA", "AMD"],
        "intent_category": "demand_or_revenue_signal",
        "intent_direction": "neutral_context",
        "confirmation_status": "reputable_reported",
    }


def test_deterministic_event_context_is_non_authoritative():
    result = deterministic_event_context(_event())

    assert result["authority"] == AI_EVENT_CONTEXT_AUTHORITY
    assert result["runtime_effect"] == "context_only_no_live_authority"
    assert result["affected_symbols"] == ["NVDA", "AMD"]
    assert result["intent"] == "demand_or_revenue_signal"


def test_provider_output_is_constrained_to_event_symbols_and_context_only():
    def provider(_prompt):
        return {
            "summary": "AI demand context for memory suppliers.",
            "intent": "constructive",
            "affected_symbols": ["NVDA", "AMD", "TSLA"],
            "market_alignment": "constructive_watch",
            "confidence": "high",
            "confirmation_status": "reputable_reported",
            "missing_evidence": [],
            "risk_notes": ["supplier signal only"],
            "authority": "approve_buy",
        }

    service = AIEventContextService(
        config=AIEventContextConfig(enabled=True, provider_name="test_provider"),
        provider=provider,
    )
    result = service.interpret(_event())

    assert result["provider"] == "test_provider"
    assert result["authority"] == AI_EVENT_CONTEXT_AUTHORITY
    assert result["runtime_effect"] == "context_only_no_live_authority"
    assert result["affected_symbols"] == ["NVDA", "AMD"]
    assert "TSLA" not in result["affected_symbols"]
    assert "ai_interpretation_context_only" in result["risk_notes"]


def test_provider_error_falls_back_safely():
    def provider(_prompt):
        raise RuntimeError("provider unavailable")

    service = AIEventContextService(
        config=AIEventContextConfig(enabled=True, provider_name="test_provider"),
        provider=provider,
    )
    result = service.interpret(_event())

    assert result["provider"] == "test_provider_error_fallback"
    assert result["authority"] == AI_EVENT_CONTEXT_AUTHORITY
    assert result["affected_symbols"] == ["NVDA", "AMD"]
    assert "provider_error" in result


def main():
    tests = [
        test_deterministic_event_context_is_non_authoritative,
        test_provider_output_is_constrained_to_event_symbols_and_context_only,
        test_provider_error_falls_back_safely,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} AI event context service tests passed.")


if __name__ == "__main__":
    main()
