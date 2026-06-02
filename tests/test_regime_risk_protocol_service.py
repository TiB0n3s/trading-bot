#!/usr/bin/env python3
"""Tests for regime-driven risk and re-entry protocols."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.regime_risk_protocol_service import (
    apply_protocol_lockout_state,
    crash_risk_protocol,
    reentry_protocol,
)


def test_crash_risk_protocol_requires_four_of_five_hits():
    decision = crash_risk_protocol(regime_history=[2, 1, 2, 2, 2]).to_dict()

    assert decision["action"] == "delta_hedge_required"
    assert decision["lockout_required"] is True
    assert decision["hedge_ratio"] == 0.5


def test_crash_risk_protocol_stands_down_on_noisy_signal():
    decision = crash_risk_protocol(regime_history=[2, 1, 2, 1, 0]).to_dict()

    assert decision["action"] == "stand_down"
    assert decision["lockout_required"] is False


def test_reentry_protocol_requires_stable_quiet_bull_and_window():
    decision = reentry_protocol(
        current_regime=0,
        stability_counter=5,
        current_status="lockout",
    ).to_dict()

    assert decision["action"] == "begin_tranched_reentry"
    assert decision["tranche_count"] == 4
    assert decision["lockout_required"] is True


def test_reentry_protocol_delays_outside_execution_window():
    decision = reentry_protocol(
        current_regime=0,
        stability_counter=5,
        within_execution_window=False,
    ).to_dict()

    assert decision["action"] == "delay_reentry"


def test_apply_protocol_lockout_state_sets_file_without_orders():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "risk_lockout.json"
        decision = crash_risk_protocol(regime_history=[2, 2, 2, 1, 2])
        result = apply_protocol_lockout_state(
            decision=decision,
            lockout_path=path,
        )

        assert result["runtime_effect"] == "persistent_state_only_no_broker_orders"
        assert result["lockout_state"]["active"] is True
        assert path.exists()


def main():
    tests = [
        test_crash_risk_protocol_requires_four_of_five_hits,
        test_crash_risk_protocol_stands_down_on_noisy_signal,
        test_reentry_protocol_requires_stable_quiet_bull_and_window,
        test_reentry_protocol_delays_outside_execution_window,
        test_apply_protocol_lockout_state_sets_file_without_orders,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} regime risk protocol tests passed.")


if __name__ == "__main__":
    main()
