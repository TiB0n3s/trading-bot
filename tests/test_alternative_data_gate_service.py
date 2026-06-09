#!/usr/bin/env python3
"""Tests for alternative-data Level 0 gate scoring."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.alternative_data_gate_service import evaluate_alternative_data_gate  # noqa: E402


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_alternative_data_gate_passes_when_no_inputs_present():
    gate = evaluate_alternative_data_gate(account_state={}, action="buy").to_dict()

    assert_equal(gate["decision"], "pass", "decision")
    assert_equal(gate["size_modifier"], 1.0, "size modifier")
    assert_equal(gate["stress_score"], 0.0, "stress")


def test_alternative_data_gate_sizes_down_on_infrastructure_degradation():
    gate = evaluate_alternative_data_gate(
        account_state={
            "hardware_telemetry": {
                "api_latency_ms": 950,
            }
        },
        action="buy",
    ).to_dict()

    assert_equal(gate["decision"], "size_down", "decision")
    assert_equal(gate["size_modifier"], 0.5, "size modifier")


def test_alternative_data_gate_vetoes_multi_category_stress():
    gate = evaluate_alternative_data_gate(
        account_state={
            "text_sentiment": {
                "sentiment_score": -0.9,
                "sentiment_velocity": -0.7,
            },
            "intermarket_effects": {
                "yield_curve_spike_score": 0.9,
                "currency_stress_score": 0.8,
            },
            "liquidity_footprints": {
                "gamma_exposure_risk": 0.85,
            },
        },
        action="buy",
    ).to_dict()

    assert_equal(gate["decision"], "veto", "decision")
    assert_equal(gate["size_modifier"], 0.0, "size modifier")


def main():
    tests = [
        test_alternative_data_gate_passes_when_no_inputs_present,
        test_alternative_data_gate_sizes_down_on_infrastructure_degradation,
        test_alternative_data_gate_vetoes_multi_category_stress,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} alternative data gate tests passed.")


if __name__ == "__main__":
    main()
