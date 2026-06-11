#!/usr/bin/env python3
"""Offline adversarial simulations for layered model degradation checks.

This script never routes orders. It injects synthetic stress into otherwise
strong paper candidates and verifies that Level 0-3 degrade conservatively.
"""

from __future__ import annotations

import argparse
import json
import random
import sys
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.layered_model_decision_service import build_layered_model_decision  # noqa: E402


def _base_account_state(symbol: str) -> dict[str, Any]:
    return {
        "symbol": symbol.upper(),
        "historical_bar_paper_strategy": {
            "status": "paper_ready",
            "master_confidence_score": 78.0,
            "paper_recommendation": "paper_size_candidate",
            "baseline_delta": 8.0,
            "liquidity_stress_bucket": "normal",
            "paper_position_size_pct": 1.2,
        },
        "prediction_gate": {"ml_prediction_score": 72.0, "prediction_decision": "pass"},
        "transformer_authority": {
            "enabled": True,
            "decision": "allow",
            "probability": 0.70,
            "status": "paper_gate",
        },
        "regime_routing_decision": {
            "regime_id": 0,
            "regime_label": "quiet_bull",
            "active_model_slot": "regime_0_model",
            "sub_model_strategy": "trend_continuation",
            "allow_new_longs": True,
            "size_modifier": 1.0,
        },
        "bar_pattern_features": {
            "atr_20_pct": 0.8,
            "vpin_toxicity_20": 0.12,
            "variance_ratio_30m": 1.18,
            "distance_from_vwap_pct": 0.6,
            "vwap_rolling_std_pct": 0.5,
            "triple_barrier_timeout_minutes": 15,
        },
        "execution_quality": {
            "decision": "allow",
            "slippage_estimate_pct": 0.02,
            "quote_instability_score": 0.10,
        },
    }


def _evaluate(name: str, state: dict[str, Any]) -> dict[str, Any]:
    payload = build_layered_model_decision(
        symbol=str(state.get("symbol") or "AAPL"),
        action="buy",
        decision={"approved": False, "position_size_pct": 1.0},
        account_state=state,
        execution_mode="paper",
        ml_authority_config={
            "historical_bar_meta_label_authority": {
                "enabled": True,
                "min_veto_score": 65.0,
                "min_approve_score": 65.0,
                "min_size_increase_score": 75.0,
                "min_baseline_delta": 0.0,
                "max_position_size_pct": 1.5,
                "can_veto": True,
            }
        },
        env={"TRANSFORMER_AUTHORITY_ENABLED": "false"},
    ).to_dict()
    return {
        "scenario": name,
        "final_instruction": payload["final_instruction"],
        "final_size_pct": payload["final_size_pct"],
        "level_0_alternative_decision": payload["level_0_alternative_gates"]["decision"],
        "level_2_effect": payload["level_2_meta_label"]["effect"],
        "level_3_reason": payload["level_3_sizing"]["reason"],
        "payload": payload,
    }


def _max_drawdown_pct(returns_pct: list[float]) -> float:
    equity = 1.0
    peak = 1.0
    max_drawdown = 0.0
    for item in returns_pct:
        equity *= 1.0 + (item / 100.0)
        peak = max(peak, equity)
        if peak > 0:
            max_drawdown = min(max_drawdown, (equity - peak) / peak * 100.0)
    return round(max_drawdown, 6)


def _noise_perturbation_check(symbol: str) -> dict[str, Any]:
    rng = random.Random(42)
    baseline = _evaluate("noise_baseline", _base_account_state(symbol))
    baseline_size = float(baseline["final_size_pct"] or 0.0)
    instructions = []
    sizes = []
    for idx in range(25):
        state = deepcopy(_base_account_state(symbol))
        state["historical_bar_paper_strategy"]["master_confidence_score"] += rng.uniform(-2.0, 2.0)
        state["prediction_gate"]["ml_prediction_score"] += rng.uniform(-2.0, 2.0)
        state["transformer_authority"]["probability"] += rng.uniform(-0.02, 0.02)
        features = state["bar_pattern_features"]
        features["vpin_toxicity_20"] += rng.uniform(-0.03, 0.03)
        features["variance_ratio_30m"] += rng.uniform(-0.05, 0.05)
        features["distance_from_vwap_pct"] += rng.uniform(-0.10, 0.10)
        result = _evaluate(f"noise_perturbation_{idx}", state)
        instructions.append(result["final_instruction"])
        sizes.append(float(result["final_size_pct"] or 0.0))
    veto_count = sum(1 for item in instructions if item == "veto")
    max_size_delta = max((abs(size - baseline_size) for size in sizes), default=0.0)
    passed = veto_count == 0 and max_size_delta <= 0.35
    return {
        "scenario": "noise_perturbation_calibration",
        "final_instruction": "stable" if passed else "unstable",
        "final_size_pct": round(sum(sizes) / len(sizes), 6) if sizes else 0.0,
        "level_0_alternative_decision": "pass",
        "level_2_effect": "noise_perturbation",
        "level_3_reason": "small perturbations should not create discontinuous output",
        "passed": passed,
        "baseline_size_pct": baseline_size,
        "sample_count": len(sizes),
        "veto_count": veto_count,
        "max_size_delta_pct": round(max_size_delta, 6),
    }


def _monte_carlo_sequence_check() -> dict[str, Any]:
    realized_returns = [
        0.42,
        -0.14,
        0.31,
        0.18,
        -0.21,
        0.37,
        0.24,
        -0.10,
        0.29,
        0.16,
        -0.18,
        0.33,
    ]
    actual_drawdown = _max_drawdown_pct(realized_returns)
    rng = random.Random(17)
    shuffled_drawdowns = []
    for _ in range(250):
        sample = list(realized_returns)
        rng.shuffle(sample)
        shuffled_drawdowns.append(_max_drawdown_pct(sample))
    sorted_drawdowns = sorted(shuffled_drawdowns)
    p95_index = max(0, min(len(sorted_drawdowns) - 1, int(len(sorted_drawdowns) * 0.05)))
    adverse_p95 = sorted_drawdowns[p95_index]
    passed = actual_drawdown >= adverse_p95
    return {
        "scenario": "monte_carlo_sequence_risk",
        "final_instruction": "stable" if passed else "sequence_risk_warning",
        "final_size_pct": 0.0,
        "level_0_alternative_decision": "not_applicable",
        "level_2_effect": "monte_carlo_reshuffle",
        "level_3_reason": "actual drawdown should not be worse than adverse reshuffle tail",
        "passed": passed,
        "actual_max_drawdown_pct": actual_drawdown,
        "adverse_reshuffle_tail_pct": adverse_p95,
        "shuffle_count": len(shuffled_drawdowns),
    }


def run_scenarios(symbol: str) -> dict[str, Any]:
    scenarios: list[dict[str, Any]] = []

    telemetry_spike = deepcopy(_base_account_state(symbol))
    telemetry_spike["hardware_telemetry"] = {
        "api_latency_zscore": 4.2,
        "api_latency_ms": 1150,
    }
    telemetry_result = _evaluate("telemetry_spike_level0_override", telemetry_spike)
    telemetry_result["passed"] = (
        telemetry_result["level_0_alternative_decision"] == "veto"
        and telemetry_result["final_instruction"] == "veto"
        and float(telemetry_result["final_size_pct"]) == 0.0
    )
    scenarios.append(telemetry_result)

    decay_trap = deepcopy(_base_account_state(symbol))
    decay_trap["multi_horizon_path"] = {
        "provider": "adversarial_tft_scaffold",
        "t5": {"probability": 0.74, "expected_return_pct": 0.22},
        "t15": {"probability": 0.68, "expected_return_pct": 0.10},
        "t60": {"probability": 0.37, "expected_return_pct": -0.35},
    }
    decay_result = _evaluate("decay_trap_level2_veto", decay_trap)
    decay_result["passed"] = (
        decay_result["level_2_effect"] == "multi_horizon_decay_veto"
        and decay_result["final_instruction"] == "veto"
    )
    scenarios.append(decay_result)
    scenarios.append(_noise_perturbation_check(symbol))
    scenarios.append(_monte_carlo_sequence_check())

    passed = all(bool(row["passed"]) for row in scenarios)
    return {
        "report_version": "adversarial_simulation_v1",
        "runtime_effect": "offline_simulation_no_order_authority",
        "symbol": symbol.upper(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "passed": passed,
        "scenario_count": len(scenarios),
        "failed_count": sum(1 for row in scenarios if not row["passed"]),
        "scenarios": scenarios,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", default="AAPL")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = run_scenarios(args.symbol)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print("Adversarial Simulation")
        print(f"runtime_effect : {payload['runtime_effect']}")
        print(f"symbol         : {payload['symbol']}")
        print(f"passed         : {payload['passed']}")
        for row in payload["scenarios"]:
            marker = "OK" if row["passed"] else "FAIL"
            print(
                f"[{marker}] {row['scenario']} final={row['final_instruction']} "
                f"size={row['final_size_pct']} l0={row['level_0_alternative_decision']} "
                f"l2={row['level_2_effect']}"
            )
    return 0 if payload["passed"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
