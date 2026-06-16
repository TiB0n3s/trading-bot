#!/usr/bin/env python3
"""Tests for research expected-value utilities."""

from __future__ import annotations

from trading_bot.research.expected_value import (
    ExpectedValueAssumptions,
    evaluate_decile_expected_value,
    evaluate_expected_value,
    round_trip_cost_pct,
    whole_share_deployment,
)


def test_expected_value_subtracts_round_trip_costs():
    assumptions = ExpectedValueAssumptions(spread_pct=0.04, slippage_pct=0.03)

    result = evaluate_expected_value([1.0, -0.5, 0.5], assumptions=assumptions)

    assert round_trip_cost_pct(assumptions) == 0.1
    assert result["gross_expected_return_pct"] == 0.333333
    assert result["net_expected_return_pct"] == 0.233333
    assert result["verdict"] == "positive_ev_after_costs"


def test_expected_value_hand_worked_oracle():
    assumptions = ExpectedValueAssumptions(
        spread_pct=0.05,
        slippage_pct=0.03,
        slippage_turns=2.0,
        commission_pct=0.0,
        account_equity=531.0,
        max_position_pct=1.0,
        reference_price=100.0,
    )

    result = evaluate_expected_value([2.0, 1.0, -0.5, -1.5], assumptions=assumptions)

    # Hand-worked oracle:
    # wins=2/4 => 50%; avg win=(2.0+1.0)/2=1.5; avg loss=(-0.5-1.5)/2=-1.0
    # gross EV=(2.0+1.0-0.5-1.5)/4=0.25
    # round-trip cost=0.05 + (0.03*2.0) = 0.11
    # net EV=0.25-0.11=0.14
    # profit factor=(2.0+1.0)/(0.5+1.5)=1.5
    # Profit factor is intentionally gross by convention; net EV carries costs.
    # whole shares=floor(531/100)=5; deployed=500; cash drag=(31/531)=5.838%
    assert result["win_rate_pct"] == 50.0
    assert result["avg_win_pct"] == 1.5
    assert result["avg_loss_pct"] == -1.0
    assert result["gross_expected_return_pct"] == 0.25
    assert result["round_trip_cost_pct"] == 0.11
    assert result["net_expected_return_pct"] == 0.14
    assert result["profit_factor"] == 1.5
    assert result["shares"] == 5
    assert result["deployed_notional"] == 500.0
    assert result["whole_share_cash_drag_pct"] == 5.838
    assert result["verdict"] == "positive_ev_after_costs"


def test_expected_value_blocks_undeployable_whole_share():
    assumptions = ExpectedValueAssumptions(
        account_equity=100.0,
        max_position_pct=1.0,
        reference_price=250.0,
    )

    result = evaluate_expected_value([10.0, 8.0], assumptions=assumptions)

    assert result["shares"] == 0
    assert result["verdict"] == "cannot_deploy_whole_share"


def test_expected_value_marks_zero_cost_model_as_not_applied():
    result = evaluate_expected_value([1.0, 0.5], assumptions=ExpectedValueAssumptions())

    assert result["round_trip_cost_pct"] == 0.0
    assert result["verdict"] == "no_cost_model_applied"


def test_whole_share_deployment_reports_cash_drag():
    result = whole_share_deployment(
        ExpectedValueAssumptions(account_equity=1000.0, max_position_pct=0.5, reference_price=180.0)
    )

    assert result["target_notional"] == 500.0
    assert result["shares"] == 2
    assert result["deployed_notional"] == 360.0
    assert result["whole_share_cash_drag_pct"] == 28.0


def test_decile_expected_value_splits_ordered_returns():
    buckets = evaluate_decile_expected_value([1, 2, 3, 4], n_buckets=2)

    assert [bucket["bucket"] for bucket in buckets] == ["D1", "D2"]
    assert buckets[0]["gross_expected_return_pct"] == 1.5
    assert buckets[1]["gross_expected_return_pct"] == 3.5
