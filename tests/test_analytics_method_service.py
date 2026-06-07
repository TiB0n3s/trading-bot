#!/usr/bin/env python3
"""Tests for analytics-method canonical coverage."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.analytics_method_service import build_analytics_method_state


def test_build_analytics_method_state_maps_existing_bot_layers():
    state = build_analytics_method_state(
        context={
            "momentum_pct": 0.2,
            "session_momentum_60m_pct": 1.1,
            "session_momentum_120m_pct": 2.4,
        },
        account_state={
            "prediction_gate": {
                "ml_prediction_score": 62,
                "ml_prediction_provider": "similarity_v0",
                "ml_prediction_runtime_effect": "observe_only_compare",
            },
            "event_context": {
                "available": True,
                "trusted_source_count": 2,
                "source_tiers": ["confirmed_financial_news"],
            },
            "setup_observation": {
                "setup_label": "confirmed_near_vwap_recovery",
                "setup_score": 72,
            },
            "strategy_memory": {
                "available": True,
                "context_matches": [{"label": "symbol", "recommendation": "favor"}],
            },
            "policy_artifacts": {"state_hash": "abc"},
            "decision_policy_outcome": {"decision": "allow"},
            "portfolio_decision": {
                "decision": "size_down",
                "incremental_var_pct": 0.5,
            },
            "execution_quality": {
                "decision": "allow",
                "spread_pct": 0.04,
            },
            "market_microstructure": {
                "microstructure_score": 0.71,
                "liquidity_state": "volume_expansion",
            },
            "downside_asymmetry": {
                "downside_score": 0.2,
            },
            "historical_bar_model_intelligence": {
                "status": "observe_only_ready",
                "runtime_effect": "observe_only_no_live_authority",
                "authority": "observe_only_report_only_no_order_sizing_or_gate_authority",
                "ready_label_count": 2,
                "label_targets": ["trend_scan_label", "triple_barrier_label"],
                "labels": [],
            },
            "historical_bar_paper_strategy": {
                "version": "historical_bar_paper_strategy_v1",
                "runtime_effect": "paper_only_recommendation_no_live_authority",
                "authority": "paper_only_recommendation_no_live_order_sizing_or_gate_authority",
                "status": "paper_ready",
                "master_confidence_score": 72.5,
                "confidence_bucket": "medium",
                "paper_recommendation": "paper_trade_candidate",
                "paper_position_size_pct": 1.2,
                "guardrails": {
                    "paper_only": True,
                    "can_block_live_trades": False,
                    "can_size_live_orders": False,
                    "can_submit_orders": False,
                },
            },
        },
    )

    assert state["runtime_effect"] == "canonical_audit_and_ml_context_only"
    assert "predictive" in state["active_families"]
    assert "descriptive" in state["active_families"]
    assert "diagnostic" in state["active_families"]
    assert "prescriptive" in state["active_families"]
    assert "sentiment_nlp" in state["active_families"]
    assert "risk_analytics" in state["active_families"]
    assert "historical_bar_ml" in state["active_families"]
    assert "paper_strategy_ensemble" in state["active_families"]
    assert "high_frequency_microstructure" in state["active_families"]
    assert state["families"]["descriptive"]["long_horizon_momentum"] is True
    assert state["families"]["risk_analytics"]["var_proxy_available"] is True
    assert state["families"]["alternative_data"]["status"] == "not_integrated"
    assert state["families"]["reinforcement_learning"]["status"] == "not_integrated"
    assert state["guardrails"]["no_new_trade_authority"] is True
    review = state["ai_review_suite"]
    assert review["r"] == "observe_only_no_live_authority"
    assert review["n"] == 10
    paper = state["historical_bar_paper_strategy"]
    assert paper["paper_recommendation"] == "paper_trade_candidate"
    assert (
        state["families"]["paper_strategy_ensemble"]["authority"]
        == "paper_only_recommendation_no_live_order_sizing_or_gate_authority"
    )


def test_build_analytics_method_state_does_not_infer_unwired_model_types():
    state = build_analytics_method_state(
        context={},
        account_state={
            "historical_bar_model_intelligence": {
                "status": "no_candidates",
                "runtime_effect": "observe_only_no_live_authority",
                "authority": "observe_only_report_only_no_order_sizing_or_gate_authority",
                "ready_label_count": 0,
                "label_targets": [],
                "labels": [],
            },
            "historical_bar_paper_strategy": {
                "version": "historical_bar_paper_strategy_v1",
                "runtime_effect": "paper_only_recommendation_no_live_authority",
                "authority": "paper_only_recommendation_no_live_order_sizing_or_gate_authority",
                "status": "not_ready",
                "paper_recommendation": "paper_observe_only_no_model_score",
                "paper_position_size_pct": 0.0,
                "guardrails": {
                    "paper_only": True,
                    "can_block_live_trades": False,
                    "can_size_live_orders": False,
                    "can_submit_orders": False,
                },
            },
        },
    )

    assert state["active_family_count"] == 0
    assert state["families"]["alternative_data"]["status"] == "not_integrated"
    assert state["families"]["reinforcement_learning"]["status"] == "not_integrated"
    assert state["families"]["high_frequency_microstructure"]["status"] == "not_integrated"


def main():
    tests = [
        test_build_analytics_method_state_maps_existing_bot_layers,
        test_build_analytics_method_state_does_not_infer_unwired_model_types,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} analytics method service tests passed.")


if __name__ == "__main__":
    main()
