#!/usr/bin/env python3
"""Decision policy authority and safety tests."""

from __future__ import annotations

import inspect
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import decision_policy  # noqa: E402


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy value")


def assert_lte(actual, expected, label):
    if actual > expected:
        raise AssertionError(f"{label}: expected <= {expected!r}, got {actual!r}")


def neutral_memory(symbol, intelligence_context=None, **kwargs):
    return {"available": True, "matches": []}


def avoid_memory(symbol, intelligence_context=None, **kwargs):
    return {
        "available": True,
        "matches": [
            {
                "label": "symbol",
                "recommendation": "avoid",
                "min_setup_score": 80,
                "reason": "test avoid memory",
            }
        ],
    }


def test_hard_gate_context_can_only_block():
    result = decision_policy.evaluate_decision_policy(
        "AAPL",
        "buy",
        intelligence_context={"summary": {"recommended_action": "allow"}},
        account_state={"macro_risk": {"block_new_buys": True}},
    )

    assert_equal(result["decision"], "block", "decision")
    assert_equal(result["size_multiplier"], 0.0, "size multiplier")
    assert_equal(result["authority_scope"], "hard_gate_mirror_for_replay_audit", "authority scope")
    assert_equal(result["can_increase_size"], False, "can increase size")
    assert_equal(result["can_submit_orders"], False, "can submit orders")


def test_policy_never_increases_size(monkeypatch=None):
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = avoid_memory
        account_state = {}
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 16, "decision": "allow"},
            },
            account_state=account_state,
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_true(result["decision"] in {"block", "size_down", "allow"}, "known decision")
    assert_lte(float(result["size_multiplier"]), 1.0, "size multiplier")
    assert_equal(result["can_increase_size"], False, "can increase size")
    assert_true("utility_estimate" in result, "utility estimate present")
    assert_true("calibrated_confidence" in account_state, "calibrated confidence present")
    assert_equal(
        account_state["calibrated_confidence"]["confidence_quality"],
        "uncalibrated_prior",
        "calibrated confidence fallback",
    )
    assert_equal(
        result["utility_estimate"]["utility_decision"] in {"trade_candidate", "do_not_trade"},
        True,
        "utility estimate is observe-only",
    )


def test_sell_signals_pass_through_without_order_authority():
    result = decision_policy.evaluate_decision_policy("AAPL", "sell")

    assert_equal(result["decision"], "allow", "sell decision")
    assert_equal(result["size_multiplier"], 1.0, "sell size multiplier")
    assert_equal(result.get("can_submit_orders"), False, "can submit orders")
    assert_equal(
        result["utility_estimate"]["utility_decision"],
        "not_applicable",
        "sell utility estimate",
    )


def test_portfolio_duplicate_risk_can_size_down_policy():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "TSM",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 90, "decision": "allow"},
            },
            account_state={
                "balance": 100_000,
                "proposed_position_size_pct": 1.0,
                "open_positions": [
                    {"symbol": "NVDA", "qty": 10, "market_value": 6_000},
                    {"symbol": "AMD", "qty": 20, "market_value": 5_000},
                ],
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "size_down", "decision")
    assert_lte(result["size_multiplier"], 0.75, "size multiplier")
    assert_equal(
        result["portfolio_decision"]["decision"],
        "size_down",
        "portfolio decision",
    )


def test_execution_quality_can_size_down_policy():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 90, "decision": "allow"},
            },
            account_state={
                "execution_quality": {
                    "decision": "size_down",
                    "size_multiplier": 0.50,
                    "net_execution_cost_pct": 0.55,
                    "fill_quality": "degraded",
                },
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "size_down", "decision")
    assert_lte(result["size_multiplier"], 0.50, "size multiplier")
    assert_equal(
        result["execution_quality"]["decision"],
        "size_down",
        "execution quality",
    )


def test_execution_quality_block_candidate_blocks_policy():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 90, "decision": "allow"},
                "prediction": {"prediction_decision": "allow", "prediction_score": 80},
            },
            account_state={
                "portfolio_decision": {"decision": "allow"},
                "execution_quality": {
                    "decision": "block",
                    "size_multiplier": 0.40,
                    "net_execution_cost_pct": 1.20,
                    "fill_quality": "poor",
                },
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "block", "execution block candidate decision")
    assert_equal(result["size_multiplier"], 0.0, "execution block candidate size")
    assert_true("execution quality says block candidate" in result["risks"], "risk reason")


def test_duplicate_portfolio_risk_blocks_even_with_strong_standalone_chart():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "TSM",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 95, "decision": "allow"},
                "prediction": {"prediction_decision": "allow", "prediction_score": 80},
            },
            account_state={
                "setup_quality": {"score": 92, "recommendation": "buy"},
                "portfolio_decision": {
                    "decision": "block",
                    "size_multiplier": 0.0,
                    "duplicate_risk_score": 0.94,
                    "crowded_theme": "semiconductors",
                },
                "execution_quality": {"decision": "allow"},
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "block", "portfolio block wins")
    assert_equal(result["size_multiplier"], 0.0, "size")
    assert_true("portfolio duplicate risk says block" in result["risks"], "risk reason")


def test_utility_estimate_cannot_block_or_size_by_itself():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 90, "decision": "allow"},
                "prediction": {"prediction_decision": "allow", "prediction_score": 80},
            },
            account_state={
                "utility_estimate": {
                    "utility_decision": "do_not_trade",
                    "portfolio_adjusted_utility_pct": -9.0,
                    "utility_scope": "telemetry_observe_only",
                },
                "portfolio_decision": {"decision": "allow"},
                "execution_quality": {"decision": "allow"},
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "allow", "utility telemetry is not authority")
    assert_equal(result["size_multiplier"], 1.0, "utility telemetry does not size")


def test_calibrated_confidence_drift_can_size_down_buy_review():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 90, "decision": "allow"},
                "prediction": {"prediction_decision": "allow", "prediction_score": 80},
            },
            account_state={
                "calibrated_confidence": {
                    "primary_source": "ml_prediction",
                    "primary_predicted_win_rate": 0.85,
                    "primary_realized_win_rate": 0.05,
                    "primary_sample_size": 500,
                    "confidence_quality": "medium",
                },
                "portfolio_decision": {"decision": "allow"},
                "execution_quality": {"decision": "allow"},
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "size_down", "calibration drift sizes down")
    assert_equal(result["size_multiplier"], 0.65, "calibration drift size multiplier")
    assert_equal(
        result["confidence_calibration_gate"]["decision"],
        "size_down",
        "calibration gate",
    )


def test_canonical_snapshot_payload_cannot_change_decision_by_itself():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 90, "decision": "allow"},
            },
            account_state={
                "canonical_intelligence_json": '{"advisory_authority_state":{"utility_estimate":{"utility_decision":"do_not_trade"}}}',
                "portfolio_decision": {"decision": "allow"},
                "execution_quality": {"decision": "allow"},
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "allow", "canonical persistence is inert")


def test_rollout_candidate_status_cannot_change_authority_by_itself():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 90, "decision": "allow"},
                "prediction": {"prediction_decision": "allow", "prediction_score": 80},
            },
            account_state={
                "rollout_contract": {
                    "report_version": "rollout_contract_v1",
                    "runtime_effect": "telemetry_only_no_live_authority",
                    "assessments": [
                        {
                            "feature_family": "portfolio_decision",
                            "status": "narrow_block_candidate",
                        },
                        {
                            "feature_family": "execution_quality",
                            "status": "size_down_candidate",
                        },
                    ],
                },
                "portfolio_decision": {"decision": "allow"},
                "execution_quality": {"decision": "allow"},
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "allow", "rollout candidates are not authority")
    assert_equal(result["size_multiplier"], 1.0, "rollout candidates do not size")


def test_symbol_pattern_observation_cannot_change_authority_by_itself():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 90, "decision": "allow"},
                "prediction": {"prediction_decision": "allow", "prediction_score": 80},
            },
            account_state={
                "pattern_state": {
                    "pattern_label": "momentum_deterioration",
                    "directional_bias": "risk_negative",
                    "favorable_move_probability": 0.05,
                    "expected_mae_pct": -3.0,
                    "authority": "observe_only_no_live_authority",
                },
                "ai_momentum_pattern": {
                    "pattern_label": "momentum_deterioration",
                    "directional_bias": "risk_negative",
                    "runtime_effect": "observe_only_no_live_authority",
                },
                "portfolio_decision": {"decision": "allow"},
                "execution_quality": {"decision": "allow"},
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "allow", "pattern telemetry is not authority")
    assert_equal(result["size_multiplier"], 1.0, "pattern telemetry does not size")


def test_historical_bar_model_artifact_cannot_change_authority_by_itself():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 90, "decision": "allow"},
                "prediction": {"prediction_decision": "allow", "prediction_score": 80},
            },
            account_state={
                "historical_bar_model_candidate": {
                    "report_version": "historical_bar_observe_training_v1",
                    "runtime_effect": "observe_only_no_live_authority",
                    "label_target": "triple_barrier_label",
                    "training": {"trained": True, "accuracy": 0.99},
                    "suggested_decision": "block",
                    "suggested_size_multiplier": 0.0,
                },
                "historical_bar_model_readiness": {
                    "status": "observe_only_candidate_ready",
                    "runtime_effect": "observe_only_report_no_live_authority",
                },
                "portfolio_decision": {"decision": "allow"},
                "execution_quality": {"decision": "allow"},
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "allow", "historical-bar artifact is not authority")
    assert_equal(result["size_multiplier"], 1.0, "historical-bar artifact does not size")


def test_promoted_transformer_authority_can_block_buy_review():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 90, "decision": "allow"},
                "prediction": {"prediction_decision": "allow", "prediction_score": 80},
            },
            account_state={
                "transformer_authority": {
                    "enabled": True,
                    "mode": "paper_gate",
                    "model_id": "transformer_test",
                    "decision": "block",
                    "probability": 0.21,
                    "reason": "test low probability",
                    "size_multiplier": 0.0,
                },
                "portfolio_decision": {"decision": "allow"},
                "execution_quality": {"decision": "allow"},
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "block", "promoted transformer authority can block")
    assert_equal(result["size_multiplier"], 0.0, "transformer block zeroes size")
    assert_true("transformer_authority" in result, "transformer signal returned")


def test_promoted_transformer_authority_can_size_down_buy_review():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 90, "decision": "allow"},
                "prediction": {"prediction_decision": "allow", "prediction_score": 80},
            },
            account_state={
                "transformer_authority": {
                    "enabled": True,
                    "mode": "paper_soft",
                    "model_id": "transformer_test",
                    "decision": "size_down",
                    "probability": 0.42,
                    "reason": "test marginal probability",
                    "size_multiplier": 0.65,
                },
                "portfolio_decision": {"decision": "allow"},
                "execution_quality": {"decision": "allow"},
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "size_down", "promoted transformer authority can size down")
    assert_equal(result["size_multiplier"], 0.65, "transformer size multiplier applied")


def test_shadow_divergence_gate_blocks_buy_review():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 90, "decision": "allow"},
                "prediction": {"prediction_decision": "allow", "prediction_score": 80},
            },
            account_state={
                "shadow_prediction_health": {
                    "status": "divergence_alert",
                    "divergence_rate": 0.5,
                    "comparable_rows": 12,
                    "thresholds": {"max_divergence_rate": 0.35},
                },
                "portfolio_decision": {"decision": "allow"},
                "execution_quality": {"decision": "allow"},
                "transformer_authority": {"decision": "allow", "probability": 0.8},
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "block", "shadow divergence blocks")
    assert_equal(result["size_multiplier"], 0.0, "shadow divergence zeroes size")
    assert_true("shadow_prediction_gate" in result, "shadow gate returned")


def test_quant_suite_asymmetric_majority_blocks_buy_review():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 90, "decision": "allow"},
                "prediction": {"prediction_decision": "allow", "prediction_score": 80},
            },
            account_state={
                "quant_model_suite": {
                    "models": [
                        {
                            "provider": "xgboost_asymmetric_false_positive",
                            "decision": "avoid",
                        },
                        {"provider": "random_forest", "decision": "block"},
                        {"provider": "baseline", "decision": "allow"},
                    ]
                },
                "portfolio_decision": {"decision": "allow"},
                "execution_quality": {"decision": "allow"},
                "transformer_authority": {"decision": "allow", "probability": 0.8},
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "block", "quant asymmetric majority blocks")
    assert_true("quant_model_suite_gate" in result, "quant gate returned")


def test_historical_bar_symbol_gate_sizes_down_low_accuracy_symbol():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 90, "decision": "allow"},
                "prediction": {"prediction_decision": "allow", "prediction_score": 80},
            },
            account_state={
                "historical_bar_model_intelligence": {
                    "labels": [
                        {
                            "label_target": "triple_barrier_label",
                            "symbol_gates": [
                                {
                                    "symbol": "AAPL",
                                    "authority_status": "blocked",
                                    "blockers": ["symbol_accuracy:0.5500<0.6000"],
                                }
                            ],
                        }
                    ]
                },
                "portfolio_decision": {"decision": "allow"},
                "execution_quality": {"decision": "allow"},
                "transformer_authority": {"decision": "allow", "probability": 0.8},
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "size_down", "historical bar symbol gate sizes down")
    assert_equal(result["size_multiplier"], 0.6, "historical bar size multiplier")
    assert_true("historical_bar_regime_gate" in result, "historical gate returned")


def test_strategy_memory_distribution_drift_sizes_down_buy_review():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 90, "decision": "allow"},
                "prediction": {"prediction_decision": "allow", "prediction_score": 80},
            },
            account_state={
                "strategy_memory_distribution_health": {
                    "version": "strategy_memory_distribution_health_v1",
                    "decision": "size_down",
                    "status": "distribution_drift",
                    "size_multiplier": 0.5,
                    "max_psi": 0.27,
                    "max_psi_feature": "vpin_toxicity_20",
                    "reason": "test PSI drift",
                },
                "portfolio_decision": {"decision": "allow"},
                "execution_quality": {"decision": "allow"},
                "transformer_authority": {"decision": "allow", "probability": 0.8},
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "size_down", "decision")
    assert_equal(result["size_multiplier"], 0.5, "distribution size multiplier")
    assert_equal(
        result["strategy_memory_distribution_gate"]["decision"],
        "size_down",
        "distribution gate",
    )


def test_ema200_macd_reversal_gate_sizes_down_adverse_buy_review():
    original = decision_policy.contextual_memory_for_signal
    try:
        decision_policy.contextual_memory_for_signal = neutral_memory
        result = decision_policy.evaluate_decision_policy(
            "AAPL",
            "buy",
            intelligence_context={
                "summary": {"recommended_action": "allow"},
                "opportunity_score": {"score": 90, "decision": "allow"},
                "prediction": {"prediction_decision": "allow", "prediction_score": 80},
            },
            account_state={
                "bar_pattern_features": {
                    "ema200_macd_reversal_signal": "short_early_reversal",
                    "price_vs_ema_200_pct": -0.42,
                    "closes_below_ema_200_5": 1,
                    "macd": -0.12,
                    "macd_signal": -0.08,
                    "macd_bearish_divergence": 1,
                },
                "portfolio_decision": {"decision": "allow"},
                "execution_quality": {"decision": "allow"},
                "transformer_authority": {"decision": "allow", "probability": 0.8},
            },
        )
    finally:
        decision_policy.contextual_memory_for_signal = original

    assert_equal(result["decision"], "size_down", "EMA200/MACD gate sizes down")
    assert_equal(result["size_multiplier"], 0.65, "EMA200/MACD size multiplier")
    assert_equal(
        result["ema200_macd_reversal_gate"]["decision"],
        "size_down",
        "EMA200/MACD gate",
    )


def test_decision_policy_module_does_not_import_order_execution():
    source = inspect.getsource(decision_policy)

    assert_true("place_order(" not in source, "place_order call not referenced")
    assert_true("submit_order(" not in source, "submit_order call not referenced")
    assert_true("from broker import" not in source, "broker not imported")


if __name__ == "__main__":
    test_hard_gate_context_can_only_block()
    print("[OK] test_hard_gate_context_can_only_block")
    test_policy_never_increases_size()
    print("[OK] test_policy_never_increases_size")
    test_sell_signals_pass_through_without_order_authority()
    print("[OK] test_sell_signals_pass_through_without_order_authority")
    test_portfolio_duplicate_risk_can_size_down_policy()
    print("[OK] test_portfolio_duplicate_risk_can_size_down_policy")
    test_execution_quality_can_size_down_policy()
    print("[OK] test_execution_quality_can_size_down_policy")
    test_execution_quality_block_candidate_blocks_policy()
    print("[OK] test_execution_quality_block_candidate_blocks_policy")
    test_duplicate_portfolio_risk_blocks_even_with_strong_standalone_chart()
    print("[OK] test_duplicate_portfolio_risk_blocks_even_with_strong_standalone_chart")
    test_utility_estimate_cannot_block_or_size_by_itself()
    print("[OK] test_utility_estimate_cannot_block_or_size_by_itself")
    test_calibrated_confidence_drift_can_size_down_buy_review()
    print("[OK] test_calibrated_confidence_drift_can_size_down_buy_review")
    test_canonical_snapshot_payload_cannot_change_decision_by_itself()
    print("[OK] test_canonical_snapshot_payload_cannot_change_decision_by_itself")
    test_rollout_candidate_status_cannot_change_authority_by_itself()
    print("[OK] test_rollout_candidate_status_cannot_change_authority_by_itself")
    test_symbol_pattern_observation_cannot_change_authority_by_itself()
    print("[OK] test_symbol_pattern_observation_cannot_change_authority_by_itself")
    test_historical_bar_model_artifact_cannot_change_authority_by_itself()
    print("[OK] test_historical_bar_model_artifact_cannot_change_authority_by_itself")
    test_promoted_transformer_authority_can_block_buy_review()
    print("[OK] test_promoted_transformer_authority_can_block_buy_review")
    test_promoted_transformer_authority_can_size_down_buy_review()
    print("[OK] test_promoted_transformer_authority_can_size_down_buy_review")
    test_shadow_divergence_gate_blocks_buy_review()
    print("[OK] test_shadow_divergence_gate_blocks_buy_review")
    test_quant_suite_asymmetric_majority_blocks_buy_review()
    print("[OK] test_quant_suite_asymmetric_majority_blocks_buy_review")
    test_historical_bar_symbol_gate_sizes_down_low_accuracy_symbol()
    print("[OK] test_historical_bar_symbol_gate_sizes_down_low_accuracy_symbol")
    test_strategy_memory_distribution_drift_sizes_down_buy_review()
    print("[OK] test_strategy_memory_distribution_drift_sizes_down_buy_review")
    test_ema200_macd_reversal_gate_sizes_down_adverse_buy_review()
    print("[OK] test_ema200_macd_reversal_gate_sizes_down_adverse_buy_review")
    test_decision_policy_module_does_not_import_order_execution()
    print("[OK] test_decision_policy_module_does_not_import_order_execution")
    print("\nAll 21 decision policy tests passed.")
