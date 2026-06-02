#!/usr/bin/env python3
"""Tests for regime switching/router contracts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.regime_switching_service import (
    detect_regime,
    model_routing_matrix,
    train_hmm_regime_model,
)


def test_detect_regime_identifies_stable_quiet_bull():
    closes = [100 + i * 0.2 for i in range(40)]
    obs = detect_regime(closes=closes, regime_history=[0, 0, 0, 0]).to_dict()

    assert obs["regime_id"] == 0
    assert obs["regime_label"] == "quiet_bull"
    assert obs["stable"] is True
    assert obs["smoothed_regime_id"] == 0
    assert obs["model_slot"] == "regime_0_model"


def test_detect_regime_identifies_high_volatility_risk():
    closes = [100, 97, 102, 94, 99, 90, 96, 88, 93, 85, 89, 82, 86, 78]
    obs = detect_regime(closes=closes, regime_history=[2, 2, 2, 2]).to_dict()

    assert obs["regime_id"] == 2
    assert obs["regime_label"] == "high_volatility_risk"
    assert obs["recommended_strategy"] == "tighten_risk_or_hedge"


def test_model_routing_matrix_has_three_classical_slots():
    matrix = model_routing_matrix()

    assert matrix["regimes"]["0"]["label"] == "quiet_bull"
    assert matrix["regimes"]["1"]["label"] == "choppy_range"
    assert matrix["regimes"]["2"]["label"] == "high_volatility_risk"
    assert matrix["guardrails"]["no_live_retraining"] is True


def test_train_hmm_regime_model_blocks_small_samples():
    result = train_hmm_regime_model(closes=[1, 2, 3])

    assert result["trained"] is False
    assert "insufficient closes" in result["reason"]


def main():
    tests = [
        test_detect_regime_identifies_stable_quiet_bull,
        test_detect_regime_identifies_high_volatility_risk,
        test_model_routing_matrix_has_three_classical_slots,
        test_train_hmm_regime_model_blocks_small_samples,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} regime switching tests passed.")


if __name__ == "__main__":
    main()
