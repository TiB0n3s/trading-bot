#!/usr/bin/env python3
"""Core risk regression tests for local hooks and CI."""

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
from services.supervised_prediction_training_service import (  # noqa: E402
    asymmetric_false_positive_logistic_objective,
)


class FakeDTrain:
    @staticmethod
    def get_label():
        return [0.0, 1.0]


@contextmanager
def temporary_env(**updates):
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


def test_asymmetric_loss_preserves_false_positive_penalty():
    grad, hess = asymmetric_false_positive_logistic_objective(
        [2.0, -2.0],
        FakeDTrain(),
        false_positive_penalty=10.0,
    )

    false_positive_grad = abs(float(grad[0]))
    false_negative_grad = abs(float(grad[1]))
    assert false_positive_grad / max(false_negative_grad, 1e-9) >= 9.5
    assert hess[0] > hess[1]


def test_slippage_kelly_zeros_toxic_order_flow_even_with_high_conviction():
    with temporary_env(
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
                "bar_pattern_features": {"vpin_toxicity_20": 0.97},
            },
        )

    assert decision.action == "zero"
    assert decision.cap_pct == 0.0
    assert decision.reason == "toxic_vpin_exceeds_0.95"
    assert decision.runtime_effect == "size_cap_only_no_approval_authority"


if __name__ == "__main__":
    tests = [
        test_asymmetric_loss_preserves_false_positive_penalty,
        test_slippage_kelly_zeros_toxic_order_flow_even_with_high_conviction,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} core risk tests passed.")
