#!/usr/bin/env python3
"""Tests for canonical intelligence snapshot construction."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.canonical_intelligence_service import (
    CANONICAL_INTELLIGENCE_VERSION,
    build_canonical_intelligence_snapshot,
)


def test_build_canonical_snapshot_collects_core_state_and_hashes():
    snapshot = build_canonical_intelligence_snapshot(
        symbol="AAPL",
        decision_ts="2026-05-31T14:30:00+00:00",
        action="buy",
        feature_semantic_version="decision_snapshot_features_v2",
        market_context_metadata={
            "market_context_mtime": "2026-05-31T14:00:00+00:00",
        },
        context={
            "macro_regime": "risk_on",
            "market_bias": "buy",
            "trend_direction": "bullish",
            "trend_strength": "confirmed",
            "momentum_direction": "rising",
            "momentum_pct": 0.25,
            "session_trend_label": "strong_uptrend",
            "session_trend_score": 4,
            "tape_bar_age_seconds": 12.5,
        },
        account_state={
            "session_momentum": {"updated_at": "2026-05-31T14:29:00+00:00"},
            "prediction_gate": {
                "ml_prediction_score": 62,
                "ml_prediction_bucket": "high_55_plus",
                "ml_prediction_confidence": "medium",
                "ml_prediction_sample_size": 31,
            },
            "setup_observation": {
                "setup_label": "near_vwap_recovery",
                "setup_policy_action": "boost",
                "setup_score": 72,
            },
            "strategy_observation": {
                "trader_brain": {
                    "score": 81,
                    "setup_type": "continuation",
                    "approved_by_scorer": True,
                }
            },
            "buy_opportunity": {
                "buy_opportunity_score": 66,
                "buy_opportunity_recommendation": "buy_candidate",
            },
            "intelligence_context": {
                "summary": {
                    "support_count": 3,
                    "risk_count": 1,
                }
            },
            "policy_artifacts": {"state_hash": "abc"},
        },
    )

    data = snapshot.to_dict()
    assert data["version"] == CANONICAL_INTELLIGENCE_VERSION
    assert data["symbol"] == "AAPL"
    assert data["regime_state"]["macro_regime"] == "risk_on"
    assert data["trend_state"]["direction"] == "bullish"
    assert data["momentum_state"]["session_label"] == "strong_uptrend"
    assert data["prediction_state"]["ml_score"] == 62
    assert data["setup_state"]["policy_action"] == "boost"
    assert data["strategy_state"]["trader_brain_score"] == 81
    assert data["opportunity_state"]["recommendation"] == "buy_candidate"
    assert data["event_state"]["support_count"] == 3
    assert data["policy_artifact_ref"]["state_hash"] == "abc"
    assert data["freshness_sec"]["market_context"] == 1800.0
    assert data["freshness_sec"]["session_momentum"] == 60.0
    assert len(data["feature_vector_hash"]) == 64


def main():
    tests = [test_build_canonical_snapshot_collects_core_state_and_hashes]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} canonical intelligence tests passed.")


if __name__ == "__main__":
    main()
