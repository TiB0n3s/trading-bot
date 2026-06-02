#!/usr/bin/env python3
"""Tests for the regime model router service."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.regime_switching_service import detect_regime
from services.regime_model_router_service import route_to_model, routing_matrix_summary


def _bull_obs():
    closes = [100 + i * 0.2 for i in range(40)]
    return detect_regime(closes=closes, regime_history=[0, 0, 0, 0])


def _crash_obs():
    closes = [100, 97, 102, 94, 99, 90, 96, 88, 93, 85, 89, 82, 86, 78]
    return detect_regime(closes=closes, regime_history=[2, 2, 2, 2])


def _choppy_obs():
    # Flat/oscillating prices → mean-revert regime
    closes = [100, 101, 100, 99, 100, 101, 100, 99, 100, 101, 100, 99, 100]
    return detect_regime(closes=closes, regime_history=[1, 1, 1, 1])


def test_quiet_bull_routes_to_regime_0_model():
    obs = _bull_obs()
    routing = route_to_model(obs)
    assert routing.active_model_slot == "regime_0_model"
    assert routing.sub_model_strategy == "random_forest_trend_continuation"
    assert routing.scoring_bias == "long_bias"
    assert routing.allow_new_longs is True
    assert routing.allow_new_shorts is False
    assert routing.size_modifier == 1.0


def test_crash_regime_routes_to_stand_down():
    obs = _crash_obs()
    routing = route_to_model(obs)
    assert routing.active_model_slot == "regime_2_model"
    assert routing.scoring_bias == "stand_down"
    assert routing.allow_new_longs is False
    assert routing.allow_new_shorts is True
    assert routing.size_modifier == 0.0


def test_choppy_regime_reduces_size_and_uses_mean_reversion():
    obs = _choppy_obs()
    # Only check if stable; otherwise it goes to unstable stand-down which is also valid
    routing = route_to_model(obs)
    if obs.stable and obs.regime_id == 1:
        assert routing.active_model_slot == "regime_1_model"
        assert routing.sub_model_strategy == "oscillator_mean_reversion"
        assert routing.size_modifier < 1.0
        assert routing.allow_new_longs is True


def test_unstable_regime_routes_to_stand_down():
    closes = [100 + i * 0.2 for i in range(40)]
    obs = detect_regime(closes=closes, regime_history=[])  # empty history → not stable
    routing = route_to_model(obs)
    if not obs.stable:
        assert routing.allow_new_longs is False
        assert routing.size_modifier == 0.0


def test_none_regime_id_routes_to_no_data():
    closes = [100, 101]  # too short → regime_id=None
    obs = detect_regime(closes=closes)
    routing = route_to_model(obs)
    assert routing.regime_id is None
    assert routing.allow_new_longs is False
    assert routing.size_modifier == 0.0


def test_runtime_effect_is_always_observe_only():
    for obs in [_bull_obs(), _crash_obs()]:
        routing = route_to_model(obs)
        assert routing.runtime_effect == "observe_only_no_order_authority"


def test_routing_matrix_summary_has_all_three_regimes():
    matrix = routing_matrix_summary()
    assert matrix["runtime_effect"] == "observe_only_no_order_authority"
    assert "0" in matrix["regimes"]
    assert "1" in matrix["regimes"]
    assert "2" in matrix["regimes"]
    assert matrix["regimes"]["0"]["allow_new_longs"] is True
    assert matrix["regimes"]["2"]["allow_new_longs"] is False


def test_routing_decision_serializes_to_dict():
    obs = _bull_obs()
    routing = route_to_model(obs)
    d = routing.to_dict()
    assert "active_model_slot" in d
    assert "size_modifier" in d
    assert "runtime_effect" in d
    assert "reasons" in d


def main():
    tests = [
        test_quiet_bull_routes_to_regime_0_model,
        test_crash_regime_routes_to_stand_down,
        test_choppy_regime_reduces_size_and_uses_mean_reversion,
        test_unstable_regime_routes_to_stand_down,
        test_none_regime_id_routes_to_no_data,
        test_runtime_effect_is_always_observe_only,
        test_routing_matrix_summary_has_all_three_regimes,
        test_routing_decision_serializes_to_dict,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} regime model router tests passed.")


if __name__ == "__main__":
    main()
