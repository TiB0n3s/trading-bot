#!/usr/bin/env python3
"""Tests for observe-only decision utility estimation."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.decision_utility_service import (
    estimate_decision_utility,
    estimate_probabilistic_edge,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_gt(actual, minimum, label):
    if not actual > minimum:
        raise AssertionError(f"{label}: expected > {minimum!r}, got {actual!r}")


def assert_lt(actual, maximum, label):
    if not actual < maximum:
        raise AssertionError(f"{label}: expected < {maximum!r}, got {actual!r}")


def _strong_buy_state():
    return {
        "buy_opportunity": {
            "buy_opportunity_score": 90,
            "buy_opportunity_recommendation": "strong_buy_candidate",
        },
        "setup_quality": {"score": 85, "recommendation": "buy"},
        "strategy_observation": {"trader_brain": {"score": 82}},
        "prediction_gate": {
            "ml_prediction_score": 70,
            "ml_prediction_compare_decision": "pass",
        },
        "session_momentum_gate": {"severity": "pass"},
        "macro_risk": {"risk_multiplier": 1.0},
        "market_regime": {
            "composite_regime": "trend_expansion",
            "liquidity_regime": "normal",
            "strategy_weights": {
                "trend_continuation": 1.35,
                "orderly_pullback": 1.15,
                "mean_reversion": 0.75,
                "momentum_chase": 1.1,
            },
        },
        "momentum": {"direction": "rising"},
    }


def _negative_state():
    return {
        "buy_opportunity": {
            "buy_opportunity_score": 15,
            "buy_opportunity_recommendation": "avoid",
        },
        "setup_quality": {"score": 20, "recommendation": "avoid"},
        "strategy_observation": {"trader_brain": {"score": 25}},
        "prediction_gate": {
            "ml_prediction_score": 30,
            "ml_prediction_compare_decision": "avoid",
        },
        "session_momentum_gate": {"severity": "hard_negative"},
        "macro_risk": {"risk_multiplier": 0.5},
        "market_regime": {
            "composite_regime": "liquidity_constrained",
            "liquidity_regime": "liquidity_thin",
            "strategy_weights": {
                "trend_continuation": 0.65,
                "orderly_pullback": 0.55,
                "mean_reversion": 1.2,
                "momentum_chase": 0.35,
            },
        },
    }


def test_probabilistic_edge_separates_strong_and_negative_contexts():
    strong = estimate_probabilistic_edge(action="buy", account_state=_strong_buy_state())
    weak = estimate_probabilistic_edge(action="buy", account_state=_negative_state())

    assert_gt(strong.probability_favorable_move, 0.7, "strong probability")
    assert_lt(weak.probability_favorable_move, 0.45, "weak probability")
    assert_gt(strong.expected_upside_pct, weak.expected_upside_pct, "upside separation")
    assert_lt(
        strong.expected_adverse_excursion_pct,
        weak.expected_adverse_excursion_pct,
        "adverse separation",
    )
    assert_equal(strong.confidence, "medium", "strong confidence")


def test_strong_buy_context_produces_positive_utility_candidate():
    estimate = estimate_decision_utility(
        action="buy",
        account_state=_strong_buy_state(),
    )

    assert_equal(estimate.utility_decision, "trade_candidate", "utility decision")
    assert_equal(estimate.confidence, "medium", "confidence")
    assert_gt(estimate.probability_favorable_move, 0.7, "probability")
    assert_gt(estimate.portfolio_adjusted_utility_pct, 0.0, "portfolio utility")
    assert_equal(
        estimate.to_dict()["edge_estimate"]["probability_favorable_move"],
        estimate.probability_favorable_move,
        "nested edge estimate",
    )
    assert_equal(estimate.to_dict()["utility_scope"], "telemetry_observe_only", "scope")
    assert_equal(
        estimate.to_dict()["threshold_scope"],
        "diagnostic_not_live_policy",
        "threshold scope",
    )
    assert_equal(
        estimate.to_dict()["telemetry_expected_value_pct"],
        estimate.expected_value_pct,
        "telemetry ev",
    )


def test_negative_context_produces_do_not_trade_observation():
    estimate = estimate_decision_utility(
        action="buy",
        account_state=_negative_state(),
    )

    assert_equal(estimate.utility_decision, "do_not_trade", "utility decision")
    assert_lt(estimate.probability_favorable_move, 0.45, "probability")
    assert_lt(estimate.portfolio_adjusted_utility_pct, 0.05, "portfolio utility")


def test_sell_is_not_applicable():
    estimate = estimate_decision_utility(action="sell")

    assert_equal(estimate.utility_decision, "not_applicable", "utility decision")
    assert_equal(estimate.confidence, "none", "confidence")
    assert_equal(estimate.expected_value_pct, 0.0, "ev")


def test_market_regime_changes_utility_without_authority():
    neutral_state = _strong_buy_state()
    neutral_state.pop("market_regime")
    regime_state = _strong_buy_state()

    neutral = estimate_decision_utility(action="buy", account_state=neutral_state)
    regime = estimate_decision_utility(action="buy", account_state=regime_state)

    assert_gt(
        regime.probability_favorable_move,
        neutral.probability_favorable_move,
        "regime probability lift",
    )
    assert_gt(regime.expected_upside_pct, neutral.expected_upside_pct, "regime upside lift")
    assert_equal(regime.utility_decision, "trade_candidate", "utility observation")


def test_calibrated_confidence_blends_probability_when_sampled():
    base_state = _strong_buy_state()
    calibrated_state = _strong_buy_state()
    calibrated_state["calibrated_confidence"] = {
        "primary_realized_win_rate": 0.55,
        "primary_predicted_win_rate": 0.58,
        "primary_sample_size": 30,
        "confidence_quality": "medium",
    }

    base = estimate_decision_utility(action="buy", account_state=base_state)
    calibrated = estimate_decision_utility(action="buy", account_state=calibrated_state)

    assert_lt(
        calibrated.probability_favorable_move,
        base.probability_favorable_move,
        "calibrated probability",
    )
    assert_equal(calibrated.utility_decision, "trade_candidate", "utility observation")


def test_portfolio_duplicate_risk_reduces_utility():
    base_state = _strong_buy_state()
    portfolio_state = _strong_buy_state()
    portfolio_state["portfolio_decision"] = {
        "decision": "size_down",
        "size_multiplier": 0.50,
        "incremental_var_pct": 1.5,
    }

    base = estimate_decision_utility(action="buy", account_state=base_state)
    adjusted = estimate_decision_utility(action="buy", account_state=portfolio_state)

    assert_lt(
        adjusted.probability_favorable_move,
        base.probability_favorable_move,
        "portfolio probability",
    )
    assert_lt(
        adjusted.portfolio_adjusted_utility_pct,
        base.portfolio_adjusted_utility_pct,
        "portfolio utility",
    )


def test_execution_quality_cost_reduces_net_edge():
    base_state = _strong_buy_state()
    execution_state = _strong_buy_state()
    execution_state["execution_quality"] = {
        "decision": "size_down",
        "size_multiplier": 0.50,
        "net_execution_cost_pct": 0.65,
    }

    base = estimate_decision_utility(action="buy", account_state=base_state)
    adjusted = estimate_decision_utility(action="buy", account_state=execution_state)

    assert_lt(adjusted.expected_value_pct, base.expected_value_pct, "expected value")
    assert_lt(
        adjusted.portfolio_adjusted_utility_pct,
        base.portfolio_adjusted_utility_pct,
        "adjusted utility",
    )
    assert_equal(adjusted.execution_cost_pct, 0.65, "execution cost")


def test_alpha_factor_aggregation_lifts_supportive_context_utility():
    base_state = _strong_buy_state()
    alpha_state = _strong_buy_state()
    alpha_state["bar_pattern_features"] = {
        "pattern_score": 88,
        "long_opportunity_score": 92,
        "vpin_toxicity_20": 0.12,
    }
    alpha_state["prediction_gate"]["ml_prediction_score"] = 82

    base = estimate_decision_utility(action="buy", account_state=base_state)
    alpha = estimate_decision_utility(action="buy", account_state=alpha_state)

    assert_gt(
        alpha.probability_favorable_move,
        base.probability_favorable_move,
        "alpha probability lift",
    )
    assert_gt(alpha.expected_upside_pct, base.expected_upside_pct, "alpha upside lift")
    assert_gt(
        alpha.portfolio_adjusted_utility_pct,
        base.portfolio_adjusted_utility_pct,
        "alpha utility lift",
    )


def test_microstructure_features_shift_probability_and_utility():
    base_state = _strong_buy_state()
    supportive_state = _strong_buy_state()
    risky_state = _strong_buy_state()
    supportive_state["market_microstructure"] = {
        "session_phase": "first_30m",
        "breakout_quality": "confirmed_expansion_breakout",
        "liquidity_state": "volume_expansion",
        "reversion_risk": "normal",
        "microstructure_score": 0.78,
        "expectancy_modifier": 1.12,
    }
    risky_state["market_microstructure"] = {
        "session_phase": "midday",
        "breakout_quality": "liquidity_vacuum_breakout",
        "liquidity_state": "liquidity_vacuum",
        "reversion_risk": "high",
        "microstructure_score": 0.22,
        "expectancy_modifier": 0.65,
    }

    base = estimate_decision_utility(action="buy", account_state=base_state)
    supportive = estimate_decision_utility(action="buy", account_state=supportive_state)
    risky = estimate_decision_utility(action="buy", account_state=risky_state)

    assert_gt(
        supportive.probability_favorable_move,
        base.probability_favorable_move,
        "supportive probability",
    )
    assert_lt(
        risky.probability_favorable_move,
        base.probability_favorable_move,
        "risky probability",
    )
    assert_gt(supportive.expected_upside_pct, base.expected_upside_pct, "upside")
    assert_lt(
        risky.portfolio_adjusted_utility_pct,
        base.portfolio_adjusted_utility_pct,
        "risky utility",
    )


def test_market_participation_confirmation_shifts_edge():
    base_state = _strong_buy_state()
    confirmed_state = _strong_buy_state()
    weak_state = _strong_buy_state()
    confirmed_state["market_participation"] = {
        "participation_state": "confirmed",
        "confirmation_score": 0.82,
        "isolated_move_risk": "low",
        "expectancy_modifier": 1.14,
    }
    weak_state["market_participation"] = {
        "participation_state": "isolated_or_weak",
        "confirmation_score": 0.22,
        "isolated_move_risk": "high",
        "expectancy_modifier": 0.70,
    }

    base = estimate_decision_utility(action="buy", account_state=base_state)
    confirmed = estimate_decision_utility(action="buy", account_state=confirmed_state)
    weak = estimate_decision_utility(action="buy", account_state=weak_state)

    assert_gt(
        confirmed.probability_favorable_move,
        base.probability_favorable_move,
        "confirmed participation probability",
    )
    assert_lt(
        weak.probability_favorable_move,
        base.probability_favorable_move,
        "weak participation probability",
    )
    assert_gt(confirmed.expected_upside_pct, base.expected_upside_pct, "confirmed upside")
    assert_lt(
        weak.portfolio_adjusted_utility_pct,
        base.portfolio_adjusted_utility_pct,
        "weak utility",
    )


def test_volatility_normalization_reduces_stretched_entry_edge():
    base_state = _strong_buy_state()
    stretched_state = _strong_buy_state()
    stretched_state["volatility_normalization"] = {
        "stretch_state": "extreme_stretch",
        "chase_risk": "high",
        "stop_quality": "too_tight_vs_excursion",
        "volatility_adjusted_score": 0.18,
        "expectancy_modifier": 0.62,
    }

    base = estimate_decision_utility(action="buy", account_state=base_state)
    stretched = estimate_decision_utility(action="buy", account_state=stretched_state)

    assert_lt(
        stretched.probability_favorable_move,
        base.probability_favorable_move,
        "stretched probability",
    )
    assert_lt(stretched.expected_upside_pct, base.expected_upside_pct, "upside")
    assert_gt(
        stretched.expected_adverse_excursion_pct,
        base.expected_adverse_excursion_pct,
        "adverse excursion",
    )
    assert_lt(
        stretched.portfolio_adjusted_utility_pct,
        base.portfolio_adjusted_utility_pct,
        "utility",
    )


def test_downside_asymmetry_reduces_probability_and_increases_adverse_excursion():
    base_state = _strong_buy_state()
    downside_state = _strong_buy_state()
    downside_state["downside_asymmetry"] = {
        "downside_state": "asymmetric_downside_high",
        "downside_score": 0.72,
        "expected_adverse_modifier": 1.4,
    }

    base = estimate_decision_utility(action="buy", account_state=base_state)
    adjusted = estimate_decision_utility(action="buy", account_state=downside_state)

    assert_lt(
        adjusted.probability_favorable_move,
        base.probability_favorable_move,
        "downside probability",
    )
    assert_gt(
        adjusted.expected_adverse_excursion_pct,
        base.expected_adverse_excursion_pct,
        "adverse excursion",
    )
    assert_lt(
        adjusted.portfolio_adjusted_utility_pct,
        base.portfolio_adjusted_utility_pct,
        "utility",
    )


def test_interaction_strong_context_bad_execution_degrades_but_stays_telemetry():
    state = _strong_buy_state()
    state["market_microstructure"] = {
        "breakout_quality": "confirmed_expansion_breakout",
        "microstructure_score": 0.78,
        "expectancy_modifier": 1.10,
    }
    good = estimate_decision_utility(action="buy", account_state=state)
    state["execution_quality"] = {
        "decision": "size_down",
        "size_multiplier": 0.50,
        "net_execution_cost_pct": 0.90,
    }
    bad_execution = estimate_decision_utility(action="buy", account_state=state)

    assert_lt(
        bad_execution.portfolio_adjusted_utility_pct,
        good.portfolio_adjusted_utility_pct,
        "bad execution utility degradation",
    )
    assert_equal(
        bad_execution.to_dict()["utility_scope"],
        "telemetry_observe_only",
        "telemetry only",
    )


def test_interaction_supportive_breakout_participation_lifts_without_authority_flag():
    base_state = _strong_buy_state()
    supportive_state = _strong_buy_state()
    supportive_state["market_microstructure"] = {
        "session_phase": "first_30m",
        "breakout_quality": "confirmed_expansion_breakout",
        "microstructure_score": 0.82,
        "expectancy_modifier": 1.12,
    }
    supportive_state["market_participation"] = {
        "participation_state": "confirmed",
        "confirmation_score": 0.84,
        "isolated_move_risk": "low",
        "expectancy_modifier": 1.15,
    }

    base = estimate_decision_utility(action="buy", account_state=base_state)
    supportive = estimate_decision_utility(action="buy", account_state=supportive_state)

    assert_gt(
        supportive.portfolio_adjusted_utility_pct,
        base.portfolio_adjusted_utility_pct,
        "supportive utility lift",
    )
    assert_equal(
        supportive.to_dict()["threshold_scope"],
        "diagnostic_not_live_policy",
        "no policy threshold authority",
    )


def test_missing_telemetry_uses_neutral_fallback_without_fake_confidence():
    estimate = estimate_decision_utility(action="buy", account_state={})

    assert_equal(estimate.confidence, "low", "fallback confidence")
    assert_equal(
        estimate.to_dict()["utility_scope"],
        "telemetry_observe_only",
        "telemetry only",
    )
    assert_equal(
        estimate.utility_decision in {"trade_candidate", "do_not_trade"}, True, "known decision"
    )


def main():
    tests = [
        test_probabilistic_edge_separates_strong_and_negative_contexts,
        test_strong_buy_context_produces_positive_utility_candidate,
        test_negative_context_produces_do_not_trade_observation,
        test_sell_is_not_applicable,
        test_market_regime_changes_utility_without_authority,
        test_calibrated_confidence_blends_probability_when_sampled,
        test_portfolio_duplicate_risk_reduces_utility,
        test_execution_quality_cost_reduces_net_edge,
        test_alpha_factor_aggregation_lifts_supportive_context_utility,
        test_microstructure_features_shift_probability_and_utility,
        test_market_participation_confirmation_shifts_edge,
        test_volatility_normalization_reduces_stretched_entry_edge,
        test_downside_asymmetry_reduces_probability_and_increases_adverse_excursion,
        test_interaction_strong_context_bad_execution_degrades_but_stays_telemetry,
        test_interaction_supportive_breakout_participation_lifts_without_authority_flag,
        test_missing_telemetry_uses_neutral_fallback_without_fake_confidence,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} decision utility service tests passed.")


if __name__ == "__main__":
    main()
