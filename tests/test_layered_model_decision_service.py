#!/usr/bin/env python3
"""Tests for the Level 0-3 layered model decision payload."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.counterfactual_learning_service import (  # noqa: E402
    train_counterfactual_veto_relaxation_model,
)
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
            "variance_ratio_30m": 1.18,
            "distance_from_vwap_pct": 0.8,
            "vwap_rolling_std_pct": 0.4,
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
    assert_equal(payload["level_0_alternative_gates"]["decision"], "pass", "alt gate")
    assert_equal(payload["level_0_regime"]["decision"], "pass", "regime")
    assert_equal(payload["level_1_expert_ensemble"]["status"], "scored", "ensemble")
    micro = payload["level_1_expert_ensemble"]["microstructure_alpha_features"]
    assert_equal(micro["regime_hint"], "trend_persistence", "variance ratio hint")
    assert_equal(micro["vwap_band_zscore"], 2.0, "vwap z")
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


def test_layered_model_decision_alternative_data_veto_overrides_strong_experts():
    state = _account_state(
        text_sentiment={"sentiment_score": -0.95, "sentiment_velocity": -0.8},
        intermarket_effects={"yield_curve_spike_score": 0.95, "currency_stress_score": 0.8},
        hardware_telemetry={"api_latency_ms": 1200},
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

    assert_equal(payload["level_0_alternative_gates"]["decision"], "veto", "alt gate")
    assert_equal(payload["final_instruction"], "veto", "final")
    assert_equal(payload["final_size_pct"], 0.0, "size")


def test_layered_model_decision_records_missed_opportunity_relaxation():
    state = _account_state(
        historical_bar_paper_strategy={
            "status": "paper_ready",
            "master_confidence_score": 63.0,
            "paper_recommendation": "paper_trade_candidate",
            "baseline_delta": 2.0,
            "liquidity_stress_bucket": "normal",
            "paper_position_size_pct": 1.1,
        },
        missed_opportunity_relaxation={"threshold_relaxation_pct": 5.0},
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

    assert_equal(
        payload["level_2_meta_label"]["missed_opportunity_relaxation_pct"],
        5.0,
        "relaxation",
    )
    assert_equal(payload["level_2_meta_label"]["effect"], "paper_approval", "effect")


def test_layered_model_decision_uses_counterfactual_unvetoer_artifact():
    def row(i, positive):
        return {
            "symbol": "AAPL",
            "timestamp": f"2026-06-0{(i % 5) + 1}T14:{i % 60:02d}:00+00:00",
            "action": "buy",
            "signal_price": 100.0,
            "rejection_reason": "meta_label:veto",
            "max_favorable_60m": 1.2 if positive else 0.2,
            "max_adverse_60m": -0.2 if positive else -0.9,
            "canonical_intelligence_json": "{}",
            "setup_score": 72 if positive else 35,
            "ret_1m": 0.05 if positive else -0.08,
            "ret_5m": 0.18 if positive else -0.22,
            "ret_15m": 0.25 if positive else -0.31,
            "range_pos_15m": 0.82 if positive else 0.22,
            "distance_from_vwap": 0.15 if positive else -0.7,
            "volume_ratio_5m": 1.8 if positive else 0.7,
            "relative_strength_5m": 0.4 if positive else -0.35,
            "spread_pct": 0.02 if positive else 0.18,
            "master_confidence_score": 63.0 if positive else 41.0,
            "ensemble_probability": 0.61 if positive else 0.42,
            "meta_label_threshold": 0.65,
            "pattern_score": 78 if positive else 30,
            "vpin_toxicity_20": 0.2 if positive else 0.8,
            "trend_scan_tstat": 2.2 if positive else -1.8,
        }

    with tempfile.TemporaryDirectory() as tmp:
        artifact = Path(tmp) / "veto_relaxation_model.json"
        train_counterfactual_veto_relaxation_model(
            rows=[row(i, i % 2 == 0) for i in range(40)],
            artifact_path=artifact,
            min_samples=20,
            min_positive=5,
        )
        drift_artifact = Path(tmp) / "concept_drift.json"
        drift_artifact.write_text('{"severe_drift": false}')
        state = _account_state(
            historical_bar_paper_strategy={
                "status": "paper_ready",
                "master_confidence_score": 63.0,
                "paper_recommendation": "paper_trade_candidate",
                "baseline_delta": 2.0,
                "liquidity_stress_bucket": "normal",
                "paper_position_size_pct": 1.1,
            },
            prediction_gate={"ml_prediction_score": 63.0},
            ret_1m=0.05,
            ret_5m=0.18,
            ret_15m=0.25,
            range_pos_15m=0.82,
            distance_from_vwap=0.15,
            volume_ratio_5m=1.8,
            relative_strength_5m=0.4,
            spread_pct=0.02,
        )
        payload = build_layered_model_decision(
            symbol="AAPL",
            action="buy",
            decision={"approved": False, "position_size_pct": 1.0},
            account_state=state,
            execution_mode="paper",
            ml_authority_config={
                **_meta_config(),
                "counterfactual_veto_relaxation": {
                    "enabled": True,
                    "artifact_path": str(artifact),
                    "drift_artifact_path": str(drift_artifact),
                },
            },
            env={"TRANSFORMER_AUTHORITY_ENABLED": "false"},
        ).to_dict()

    unveto = payload["level_2_meta_label"]["counterfactual_veto_relaxation"]
    assert_equal(unveto["status"], "active", "unveto status")
    assert_true(unveto["threshold_relaxation_pct"] > 0, "unveto relaxation")
    assert_equal(payload["level_2_meta_label"]["effect"], "paper_approval", "effect")


def test_layered_model_decision_vetoes_multi_horizon_medium_decay():
    state = _account_state(
        historical_bar_paper_strategy={
            "status": "paper_ready",
            "master_confidence_score": 69.0,
            "paper_recommendation": "paper_trade_candidate",
            "baseline_delta": 2.0,
            "liquidity_stress_bucket": "normal",
            "paper_position_size_pct": 1.1,
        },
        prediction_gate={"ml_prediction_score": 68.0},
        transformer_authority={"probability": 0.68, "decision": "allow"},
        multi_horizon_path={
            "provider": "tft_scaffold",
            "t5": {"probability": 0.72, "expected_return_pct": 0.18},
            "t15": {"probability": 0.66, "expected_return_pct": 0.09},
            "t60": {"probability": 0.38, "expected_return_pct": -0.28},
        },
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

    path = payload["level_1_expert_ensemble"]["multi_horizon_path"]
    assert_equal(path["status"], "scored", "path status")
    assert_equal(path["medium_term_decay_risk"], True, "decay risk")
    assert_equal(payload["level_2_meta_label"]["effect"], "multi_horizon_decay_veto", "effect")
    assert_equal(payload["final_instruction"], "veto", "final")


def test_layered_model_decision_applies_regime_model_weight_multipliers():
    state = _account_state(
        regime_model_weight_multipliers={
            "historical_bar_ensemble": 0.5,
            "transformer_authority": 1.4,
            "supervised_prediction": 1.0,
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

    ensemble = payload["level_1_expert_ensemble"]
    experts = {row["expert"]: row for row in ensemble["experts"]}
    assert_equal(
        ensemble["regime_model_weight_multipliers"]["multipliers"]["historical_bar_ensemble"],
        0.5,
        "regime multiplier payload",
    )
    assert_equal(
        experts["historical_bar_ensemble"]["regime_weight_multiplier"],
        0.5,
        "historical multiplier",
    )
    assert_equal(
        experts["transformer_authority"]["regime_weight_multiplier"],
        1.4,
        "transformer multiplier",
    )


def main():
    tests = [
        test_layered_model_decision_approves_and_sizes_strong_stack,
        test_layered_model_decision_vetoes_weak_meta_label,
        test_layered_model_decision_regime_standdown_overrides_strong_experts,
        test_layered_model_decision_alternative_data_veto_overrides_strong_experts,
        test_layered_model_decision_records_missed_opportunity_relaxation,
        test_layered_model_decision_uses_counterfactual_unvetoer_artifact,
        test_layered_model_decision_vetoes_multi_horizon_medium_decay,
        test_layered_model_decision_applies_regime_model_weight_multipliers,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} layered model decision tests passed.")


if __name__ == "__main__":
    main()
