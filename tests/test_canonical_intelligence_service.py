#!/usr/bin/env python3
"""Tests for canonical intelligence snapshot construction."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.canonical_intelligence_service import (
    CANONICAL_INTELLIGENCE_VERSION,
    CANONICAL_INTELLIGENCE_MAX_JSON_BYTES,
    CANONICAL_INTELLIGENCE_REQUIRED_SECTIONS,
    build_canonical_intelligence_snapshot,
    canonical_json_size_bytes,
    validate_canonical_snapshot_contract,
)


def _snapshot(**overrides):
    args = {
        "symbol": "AAPL",
        "decision_ts": "2026-05-31T14:30:00+00:00",
        "action": "buy",
        "feature_semantic_version": "decision_snapshot_features_v2",
        "market_context_metadata": {
            "market_context_mtime": "2026-05-31T14:00:00+00:00",
        },
        "context": {
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
        "account_state": {
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
    }
    args.update(overrides)
    return build_canonical_intelligence_snapshot(**args)


def test_build_canonical_snapshot_collects_core_state_and_hashes():
    snapshot = _snapshot()

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


def test_canonical_snapshot_contract_requires_sections_and_size_limit():
    snapshot = _snapshot()
    result = validate_canonical_snapshot_contract(snapshot)

    assert result["ok"] is True
    assert result["missing_sections"] == []
    assert result["json_size_bytes"] <= CANONICAL_INTELLIGENCE_MAX_JSON_BYTES
    for section in CANONICAL_INTELLIGENCE_REQUIRED_SECTIONS:
        assert section in snapshot.to_dict()


def test_canonical_hash_is_stable_for_dict_insertion_order():
    first = _snapshot(
        context={
            "macro_regime": "risk_on",
            "market_bias": "buy",
            "trend_direction": "bullish",
            "trend_strength": "confirmed",
            "momentum_pct": 0.25,
        },
        account_state={
            "prediction_gate": {
                "ml_prediction_score": 62,
                "ml_prediction_bucket": "high_55_plus",
            },
            "setup_observation": {
                "setup_label": "near_vwap_recovery",
                "setup_policy_action": "boost",
            },
        },
    )
    second = _snapshot(
        context={
            "momentum_pct": 0.25,
            "trend_strength": "confirmed",
            "trend_direction": "bullish",
            "market_bias": "buy",
            "macro_regime": "risk_on",
        },
        account_state={
            "setup_observation": {
                "setup_policy_action": "boost",
                "setup_label": "near_vwap_recovery",
            },
            "prediction_gate": {
                "ml_prediction_bucket": "high_55_plus",
                "ml_prediction_score": 62,
            },
        },
    )

    assert first.feature_vector_hash == second.feature_vector_hash


def test_canonical_hash_normalizes_float_formatting():
    first = _snapshot(context={"momentum_pct": 0.1 + 0.2})
    second = _snapshot(context={"momentum_pct": 0.3})

    assert first.feature_vector_hash == second.feature_vector_hash


def test_canonical_snapshot_distinguishes_absent_null_and_empty_list_semantics():
    absent = _snapshot(account_state={"intelligence_context": {"summary": {}}})
    explicit_null = _snapshot(
        account_state={
            "intelligence_context": {
                "summary": {
                    "primary_supports": None,
                    "primary_risks": None,
                }
            }
        }
    )
    empty_list = _snapshot(
        account_state={
            "intelligence_context": {
                "summary": {
                    "primary_supports": [],
                    "primary_risks": [],
                }
            }
        }
    )

    # Absent and explicit null are equivalent because the canonical schema
    # materializes all known fields as null. Empty lists are meaningful.
    assert absent.feature_vector_hash == explicit_null.feature_vector_hash
    assert absent.feature_vector_hash != empty_list.feature_vector_hash


def test_canonical_snapshot_stays_below_size_limit():
    snapshot = _snapshot()
    assert canonical_json_size_bytes(snapshot) < CANONICAL_INTELLIGENCE_MAX_JSON_BYTES


def main():
    tests = [
        test_build_canonical_snapshot_collects_core_state_and_hashes,
        test_canonical_snapshot_contract_requires_sections_and_size_limit,
        test_canonical_hash_is_stable_for_dict_insertion_order,
        test_canonical_hash_normalizes_float_formatting,
        test_canonical_snapshot_distinguishes_absent_null_and_empty_list_semantics,
        test_canonical_snapshot_stays_below_size_limit,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} canonical intelligence tests passed.")


if __name__ == "__main__":
    main()
