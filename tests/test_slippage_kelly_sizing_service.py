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
    assert data["enabled"] is True
    assert data["runtime_effect"] == "size_cap_only_no_approval_authority"
    assert data["action"] == "cap"
    assert 0 < data["cap_pct"] < 2.0
    assert data["adjusted_risk_reward_ratio"] < 2.0 / 1.5


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


def main():
    tests = [
        test_slippage_kelly_caps_size_when_edge_is_positive_but_thinner,
        test_slippage_kelly_zeroes_trade_when_friction_exceeds_threshold,
        test_slippage_kelly_missing_inputs_is_observational_no_cap,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} slippage Kelly sizing tests passed.")


if __name__ == "__main__":
    main()
