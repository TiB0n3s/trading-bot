#!/usr/bin/env python3
"""Tests for slippage-adjusted Kelly sizing."""

from __future__ import annotations

import os
import sys
from contextlib import contextmanager
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.slippage_kelly_sizing_service import (  # noqa: E402
    calculate_slippage_adjusted_kelly_cap,
)


@contextmanager
def _temporary_env(**updates):
    original = {key: os.environ.get(key) for key in updates}
    for key, value in updates.items():
        if value is None:
            os.environ.pop(key, None)
        else:
            os.environ[key] = str(value)
    try:
        yield
    finally:
        for key, value in original.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def test_slippage_kelly_caps_size_when_edge_is_positive_but_thinner():
    # prob=0.55 clears the +0.25% net-EV bar (net EV ~0.33%), and the Kelly
    # fraction caps the large requested size.
    with _temporary_env(
        SLIPPAGE_KELLY_SIZING_ENABLED="true",
        SLIPPAGE_KELLY_FRACTION="0.25",
        SLIPPAGE_KELLY_MAX_FRICTION_RATIO="0.20",
    ):
        decision = calculate_slippage_adjusted_kelly_cap(
            action="buy",
            requested_size_pct=10.0,
            account_state={
                "prediction_gate": {"ml_prediction_score": 0.55},
                "atr_20_pct": 1.0,
                "execution_quality": {"slippage_estimate_pct": 0.05},
            },
        )

    data = decision.to_dict()
    assert data["enabled"] is True
    assert data["runtime_effect"] == "size_cap_only_no_approval_authority"
    assert data["action"] == "cap"
    assert 0 < data["cap_pct"] < 10.0
    assert data["adjusted_risk_reward_ratio"] < 2.0 / 1.5
    assert data["net_ev_after_cost_pct"] >= 0.25


def test_slippage_kelly_zeroes_when_net_ev_below_bar():
    # prob=0.50 with this reward/risk yields net EV ~0.15%, below the +0.25%
    # per-name deployability bar (#11), so the size is zeroed.
    with _temporary_env(
        SLIPPAGE_KELLY_SIZING_ENABLED="true",
        SLIPPAGE_KELLY_FRACTION="0.25",
        SLIPPAGE_KELLY_MAX_FRICTION_RATIO="0.20",
    ):
        decision = calculate_slippage_adjusted_kelly_cap(
            action="buy",
            requested_size_pct=2.0,
            account_state={
                "prediction_gate": {"ml_prediction_score": 0.50},
                "atr_20_pct": 1.0,
                "execution_quality": {"slippage_estimate_pct": 0.05},
            },
        )

    data = decision.to_dict()
    assert data["action"] == "zero"
    assert data["cap_pct"] == 0.0
    assert "net_ev_after_cost" in data["reason"]
    assert data["net_ev_after_cost_pct"] < 0.25


def test_slippage_kelly_zeroes_trade_when_friction_exceeds_threshold():
    with _temporary_env(
        SLIPPAGE_KELLY_SIZING_ENABLED="true",
        SLIPPAGE_KELLY_MAX_FRICTION_RATIO="0.20",
    ):
        decision = calculate_slippage_adjusted_kelly_cap(
            action="buy",
            requested_size_pct=1.0,
            account_state={
                "prediction_gate": {"ml_prediction_score": 0.70},
                "atr_20_pct": 1.0,
                "execution_quality": {"slippage_estimate_pct": 0.25},
            },
        )

    assert decision.action == "zero"
    assert decision.cap_pct == 0.0
    assert decision.reason == "friction_ratio_exceeds_0.20"


def test_slippage_kelly_missing_inputs_is_observational_no_cap():
    decision = calculate_slippage_adjusted_kelly_cap(
        action="buy",
        requested_size_pct=1.0,
        account_state={"execution_quality": {"slippage_estimate_pct": 0.05}},
    )

    assert decision.action == "none"
    assert decision.cap_pct is None
    assert decision.reason == "missing_model_probability"


def test_slippage_kelly_scales_down_for_elevated_liquidity_stress():
    with _temporary_env(
        SLIPPAGE_KELLY_SIZING_ENABLED="true",
        SLIPPAGE_KELLY_FRACTION="0.25",
        SLIPPAGE_KELLY_LSI_ELEVATED_MULT="0.50",
    ):
        baseline = calculate_slippage_adjusted_kelly_cap(
            action="buy",
            requested_size_pct=4.0,
            account_state={
                "prediction_gate": {"ml_prediction_score": 0.70},
                "atr_20_pct": 1.0,
                "execution_quality": {"slippage_estimate_pct": 0.05},
            },
        )
        stressed = calculate_slippage_adjusted_kelly_cap(
            action="buy",
            requested_size_pct=4.0,
            account_state={
                "prediction_gate": {"ml_prediction_score": 0.70},
                "atr_20_pct": 1.0,
                "execution_quality": {"slippage_estimate_pct": 0.05},
                "historical_bar_paper_strategy": {
                    "liquidity_stress_score": 55,
                    "liquidity_stress_bucket": "elevated",
                },
            },
        )

    assert stressed.action == "cap"
    assert stressed.reason == "slippage_adjusted_kelly_cap:lsi_elevated"
    assert stressed.liquidity_stress_bucket == "elevated"
    assert stressed.liquidity_stress_size_multiplier == 0.5
    assert stressed.cap_pct < baseline.cap_pct


def test_slippage_kelly_zeroes_for_toxic_vpin_even_with_high_conviction():
    with _temporary_env(
        SLIPPAGE_KELLY_SIZING_ENABLED="true",
        SLIPPAGE_KELLY_TOXIC_VPIN_ZERO_THRESHOLD="0.95",
    ):
        decision = calculate_slippage_adjusted_kelly_cap(
            action="buy",
            requested_size_pct=2.0,
            account_state={
                "prediction_gate": {"ml_prediction_score": 0.90},
                "atr_20_pct": 1.0,
                "execution_quality": {"slippage_estimate_pct": 0.05},
                "bar_pattern_features": {
                    "vpin_toxicity_20": 0.97,
                },
            },
        )

    assert decision.action == "zero"
    assert decision.cap_pct == 0.0
    assert decision.reason == "toxic_vpin_exceeds_0.95"
    assert decision.liquidity_stress_size_multiplier == 0.0


def test_slippage_kelly_zeroes_when_short_horizon_alpha_friction_is_too_high():
    with _temporary_env(
        SLIPPAGE_KELLY_SIZING_ENABLED="true",
        SLIPPAGE_KELLY_MAX_FRICTION_RATIO="0.50",
        SLIPPAGE_KELLY_MAX_ALPHA_FRICTION_RATIO="0.35",
    ):
        decision = calculate_slippage_adjusted_kelly_cap(
            action="buy",
            requested_size_pct=1.0,
            account_state={
                "prediction_gate": {"ml_prediction_score": 0.85},
                "bar_pattern_features": {
                    "atr_20_pct": 1.0,
                    "triple_barrier_timeout_minutes": 5,
                },
                "execution_quality": {"slippage_estimate_pct": 0.18},
            },
        )

    assert decision.action == "zero"
    assert decision.cap_pct == 0.0
    assert decision.reason == "alpha_friction_ratio_exceeds_0.35"
    assert decision.alpha_friction_ratio is not None


def test_slippage_kelly_scales_down_for_quote_instability():
    with _temporary_env(
        SLIPPAGE_KELLY_SIZING_ENABLED="true",
        SLIPPAGE_KELLY_MAX_FRICTION_RATIO="0.50",
    ):
        stable = calculate_slippage_adjusted_kelly_cap(
            action="buy",
            requested_size_pct=1.0,
            account_state={
                "prediction_gate": {"ml_prediction_score": 0.90},
                "bar_pattern_features": {"atr_20_pct": 1.0},
                "execution_quality": {"slippage_estimate_pct": 0.03},
            },
        )
        unstable = calculate_slippage_adjusted_kelly_cap(
            action="buy",
            requested_size_pct=1.0,
            account_state={
                "prediction_gate": {"ml_prediction_score": 0.90},
                "bar_pattern_features": {"atr_20_pct": 1.0},
                "execution_quality": {
                    "slippage_estimate_pct": 0.03,
                    "quote_instability_score": 0.70,
                },
            },
        )

    assert unstable.quote_instability_multiplier == 0.5
    assert unstable.cap_pct < stable.cap_pct
    assert "quote_instability" in unstable.reason


def test_slippage_kelly_pareto_caps_high_mae_risk():
    with _temporary_env(
        SLIPPAGE_KELLY_SIZING_ENABLED="true",
        SLIPPAGE_KELLY_MAX_FRICTION_RATIO="0.50",
        SLIPPAGE_KELLY_PARETO_SELECTION_ENABLED="true",
    ):
        decision = calculate_slippage_adjusted_kelly_cap(
            action="buy",
            requested_size_pct=2.0,
            account_state={
                "prediction_gate": {"ml_prediction_score": 0.90},
                "bar_pattern_features": {"atr_20_pct": 1.0},
                "execution_quality": {"slippage_estimate_pct": 0.03},
                "risk_forecast": {"expected_mae_60m_pct": 2.0},
            },
        )

    data = decision.to_dict()
    pareto = data["pareto_frontier_selection"]
    assert pareto["enabled"] is True
    assert pareto["selected_objective"] == "mae_conservation_cap_pct"
    assert decision.cap_pct <= 1.0
    assert "pareto" in decision.reason


def test_slippage_kelly_pareto_caps_turnover_cost():
    with _temporary_env(
        SLIPPAGE_KELLY_SIZING_ENABLED="true",
        SLIPPAGE_KELLY_MAX_FRICTION_RATIO="0.50",
        SLIPPAGE_KELLY_PARETO_SELECTION_ENABLED="true",
    ):
        decision = calculate_slippage_adjusted_kelly_cap(
            action="buy",
            requested_size_pct=2.0,
            account_state={
                "prediction_gate": {"ml_prediction_score": 0.90},
                "bar_pattern_features": {
                    "atr_20_pct": 1.0,
                    "triple_barrier_timeout_minutes": 15,
                },
                "execution_quality": {"slippage_estimate_pct": 0.13},
            },
        )

    pareto = decision.pareto_frontier_selection
    assert pareto is not None
    assert pareto["selected_objective"] == "turnover_cost_cap_pct"
    assert decision.cap_pct <= 1.6
    assert "pareto" in decision.reason


def main():
    tests = [
        test_slippage_kelly_caps_size_when_edge_is_positive_but_thinner,
        test_slippage_kelly_zeroes_trade_when_friction_exceeds_threshold,
        test_slippage_kelly_missing_inputs_is_observational_no_cap,
        test_slippage_kelly_scales_down_for_elevated_liquidity_stress,
        test_slippage_kelly_zeroes_for_toxic_vpin_even_with_high_conviction,
        test_slippage_kelly_zeroes_when_short_horizon_alpha_friction_is_too_high,
        test_slippage_kelly_scales_down_for_quote_instability,
        test_slippage_kelly_pareto_caps_high_mae_risk,
        test_slippage_kelly_pareto_caps_turnover_cost,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} slippage Kelly sizing tests passed.")


if __name__ == "__main__":
    main()
