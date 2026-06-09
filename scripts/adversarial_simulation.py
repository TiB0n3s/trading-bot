#!/usr/bin/env python3
"""Offline adversarial simulations for layered model degradation checks.

This script never routes orders. It injects synthetic stress into otherwise
strong paper candidates and verifies that Level 0-3 degrade conservatively.
"""

from __future__ import annotations

import argparse
import json
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
