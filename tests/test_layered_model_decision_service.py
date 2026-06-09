#!/usr/bin/env python3
"""Tests for the Level 0-3 layered model decision payload."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.layered_model_decision_service import (  # noqa: E402
    build_layered_model_decision,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy value, got {value!r}")


def _meta_config(**overrides):
    config = {
        "enabled": True,
        "min_veto_score": 65.0,
        "min_approve_score": 65.0,
        "min_size_increase_score": 75.0,
        "min_baseline_delta": 0.0,
        "max_position_size_pct": 1.5,
        "can_veto": True,
    }
    config.update(overrides)
    return {"historical_bar_meta_label_authority": config}


def _account_state(**overrides):
    state = {
        "historical_bar_paper_strategy": {
            "status": "paper_ready",
            "master_confidence_score": 78.0,
            "paper_recommendation": "paper_size_candidate",
            "baseline_delta": 8.0,
            "liquidity_stress_bucket": "normal",
            "paper_position_size_pct": 1.4,
        },
        "prediction_gate": {"ml_prediction_score": 72.0, "prediction_decision": "pass"},
        "transformer_authority": {
            "enabled": True,
            "decision": "allow",
            "probability": 0.68,
            "status": "paper_gate",
        },
        "regime_routing_decision": {
            "regime_id": 0,
            "regime_label": "quiet_bull",
            "active_model_slot": "regime_0_model",
            "sub_model_strategy": "random_forest_trend_continuation",
            "allow_new_longs": True,
            "size_modifier": 1.0,
        },
        "bar_pattern_features": {
            "atr_20_pct": 0.8,
            "vpin_toxicity_20": 0.15,
        },
        "execution_quality": {
            "decision": "allow",
            "slippage_estimate_pct": 0.02,
        },
    }
    state.update(overrides)
    return state


def test_layered_model_decision_approves_and_sizes_strong_stack():
    payload = build_layered_model_decision(
        symbol="AAPL",
        action="buy",
        decision={"approved": False, "position_size_pct": 1.0},
        account_state=_account_state(),
        execution_mode="paper",
        ml_authority_config=_meta_config(),
        env={"TRANSFORMER_AUTHORITY_ENABLED": "false"},
    ).to_dict()

    assert_equal(payload["version"], "layered_model_decision_v1", "version")
    assert_equal(payload["level_0_regime"]["decision"], "pass", "regime")
    assert_equal(payload["level_1_expert_ensemble"]["status"], "scored", "ensemble")
    assert_equal(payload["level_2_meta_label"]["effect"], "paper_approval", "meta effect")
    assert_true(payload["final_size_pct"] > 0, "final size")
    assert payload["final_instruction"] in {"paper_approval", "pass", "watch"}


def test_layered_model_decision_vetoes_weak_meta_label():
    state = _account_state(
        historical_bar_paper_strategy={
            "status": "paper_ready",
            "master_confidence_score": 50.0,
            "paper_recommendation": "paper_avoid",
            "baseline_delta": -4.0,
            "liquidity_stress_bucket": "normal",
            "paper_position_size_pct": 0.0,
        },
        prediction_gate={"ml_prediction_score": 45.0},
        transformer_authority={"probability": 0.45, "decision": "size_down"},
    )
    payload = build_layered_model_decision(
        symbol="AAPL",
        action="buy",
        decision={"approved": True, "position_size_pct": 1.0},
        account_state=state,
        execution_mode="paper",
        ml_authority_config=_meta_config(),
        env={"TRANSFORMER_AUTHORITY_ENABLED": "false"},
    ).to_dict()

    assert_equal(payload["level_2_meta_label"]["instruction"], "veto", "meta instruction")
    assert_equal(payload["final_instruction"], "veto", "final")
    assert_equal(payload["final_size_pct"], 0.0, "size")


def test_layered_model_decision_regime_standdown_overrides_strong_experts():
    state = _account_state(
        regime_routing_decision={
            "regime_id": 2,
            "regime_label": "high_volatility",
            "active_model_slot": "regime_2_model",
            "sub_model_strategy": "crash_standdown",
            "allow_new_longs": False,
            "size_modifier": 0.0,
        }
    )
    payload = build_layered_model_decision(
        symbol="AAPL",
        action="buy",
        decision={"approved": False, "position_size_pct": 1.0},
        account_state=state,
        execution_mode="paper",
        ml_authority_config=_meta_config(),
        env={"TRANSFORMER_AUTHORITY_ENABLED": "false"},
    ).to_dict()

    assert_equal(payload["level_0_regime"]["decision"], "veto", "regime")
    assert_equal(payload["final_instruction"], "veto", "final")
    assert_equal(payload["final_size_pct"], 0.0, "size")


def main():
    tests = [
        test_layered_model_decision_approves_and_sizes_strong_stack,
        test_layered_model_decision_vetoes_weak_meta_label,
        test_layered_model_decision_regime_standdown_overrides_strong_experts,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} layered model decision tests passed.")


if __name__ == "__main__":
    main()
