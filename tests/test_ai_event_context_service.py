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
    SelectiveAIEventContextService,
    deterministic_event_context,
    infer_information_novelty,
    infer_positioning_effect,
    should_use_semantic_event_provider,
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
    assert result["information_novelty"] == "new_fundamental_information"
    assert result["positioning_effect"] == "neutral_positioning_context"


def test_provider_output_is_constrained_to_event_symbols_and_context_only():
    def provider(_prompt):
        return {
            "summary": "AI demand context for memory suppliers.",
            "intent": "constructive",
            "affected_symbols": ["NVDA", "AMD", "TSLA"],
            "market_alignment": "constructive_watch",
            "information_novelty": "new_fundamental_information",
            "positioning_effect": "constructive_expectation_reset",
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
    assert result["information_novelty"] == "new_fundamental_information"
    assert result["positioning_effect"] == "constructive_expectation_reset"
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


def test_semantic_event_provider_selection_requires_trusted_high_value_context():
    routine = {
        **_event(),
        "source_tier": "unclassified",
        "event_type": "industry_demand",
        "expected_market_impact": "neutral",
        "trade_relevance": "watch_only",
        "net_event_score": 12,
    }
    high_value = {
        **_event(),
        "source_tier": "confirmed_financial_news",
        "event_type": "guidance",
        "expected_market_impact": "moderately_bullish",
        "trade_relevance": "caution",
        "net_event_score": 8,
    }

    assert should_use_semantic_event_provider(routine) is False
    assert should_use_semantic_event_provider(high_value) is True


def test_selective_service_uses_semantic_provider_only_for_high_value_events():
    calls = []

    def provider(_prompt):
        calls.append("semantic")
        return {
            "summary": "High-value event needs semantic review.",
            "intent": "guidance_catalyst",
            "affected_symbols": ["NVDA", "AMD"],
            "market_alignment": "constructive_watch",
            "confidence": "medium",
            "confirmation_status": "reputable_reported",
            "missing_evidence": [],
            "risk_notes": ["semantic test"],
        }

    service = SelectiveAIEventContextService(
        semantic_service=AIEventContextService(
            config=AIEventContextConfig(enabled=True, provider_name="test_semantic"),
            provider=provider,
        )
    )

    low_value = {
        **_event(),
        "source_tier": "unclassified",
        "event_type": "industry_demand",
        "expected_market_impact": "neutral",
        "trade_relevance": "watch_only",
        "net_event_score": 0,
    }
    high_value = {
        **_event(),
        "source_tier": "confirmed_financial_news",
        "event_type": "guidance",
        "expected_market_impact": "moderately_bullish",
        "trade_relevance": "caution",
        "net_event_score": 8,
    }

    low = service.interpret(low_value)
    high = service.interpret(high_value)

    assert calls == ["semantic"]
    assert low["provider"] == "deterministic_fallback"
    assert low["selection_policy"] == "deterministic_low_value_or_untrusted_event"
    assert high["provider"] == "test_semantic"
    assert high["selection_policy"] == "semantic_high_value_event"
    assert high["authority"] == AI_EVENT_CONTEXT_AUTHORITY


def test_positioning_and_new_information_examples_for_broadcom_and_oracle():
    broadcom = {
        "symbol": "AVGO",
        "event_type": "guidance",
        "event_summary": (
            "Broadcom raises AI revenue forecast after stronger hyperscaler "
            "chip orders and backlog beat estimates"
        ),
        "source_tier": "confirmed_financial_news",
        "expected_market_impact": "moderately_bullish",
        "intent_direction": "constructive",
        "confirmation_status": "reputable_reported",
    }
    oracle = {
        "symbol": "ORCL",
        "event_type": "earnings",
        "event_summary": (
            "Oracle cloud infrastructure bookings beat expectations and "
            "management raises guidance on new AI customer demand"
        ),
        "source_tier": "confirmed_financial_news",
        "expected_market_impact": "moderately_bullish",
        "intent_direction": "constructive",
        "confirmation_status": "reputable_reported",
    }
    recycled = {
        "symbol": "AVGO",
        "event_type": "industry_demand",
        "event_summary": "Why shares could move as investors discuss AI demand speculation",
        "source_tier": "unclassified",
        "expected_market_impact": "neutral",
        "intent_direction": "neutral_context",
        "confirmation_status": "unconfirmed",
    }

    for event in (broadcom, oracle):
        assert infer_information_novelty(event) == "new_fundamental_information"
        assert infer_positioning_effect(event) == "constructive_expectation_reset"
        context = deterministic_event_context(event)
        assert context["information_novelty"] == "new_fundamental_information"
        assert context["positioning_effect"] == "constructive_expectation_reset"

    assert infer_information_novelty(recycled) == "unconfirmed_or_recycled_narrative"
    assert infer_positioning_effect(recycled) == "neutral_positioning_context"


def main():
    tests = [
        test_deterministic_event_context_is_non_authoritative,
        test_provider_output_is_constrained_to_event_symbols_and_context_only,
        test_provider_error_falls_back_safely,
        test_semantic_event_provider_selection_requires_trusted_high_value_context,
        test_selective_service_uses_semantic_provider_only_for_high_value_events,
        test_positioning_and_new_information_examples_for_broadcom_and_oracle,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} AI event context service tests passed.")


if __name__ == "__main__":
    main()
