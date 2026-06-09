#!/usr/bin/env python3
"""Tests for offline adversarial simulation scenarios."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from scripts.adversarial_simulation import run_scenarios  # noqa: E402


def test_adversarial_simulation_scenarios_pass():
    payload = run_scenarios("AAPL")

    assert payload["passed"] is True
    scenarios = {row["scenario"]: row for row in payload["scenarios"]}
    assert scenarios["telemetry_spike_level0_override"]["level_0_alternative_decision"] == "veto"
    assert scenarios["telemetry_spike_level0_override"]["final_size_pct"] == 0.0
    assert scenarios["decay_trap_level2_veto"]["level_2_effect"] == "multi_horizon_decay_veto"


def main():
    tests = [test_adversarial_simulation_scenarios_pass]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} adversarial simulation tests passed.")


if __name__ == "__main__":
    main()
