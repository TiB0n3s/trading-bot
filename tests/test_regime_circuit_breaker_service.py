#!/usr/bin/env python3
"""Tests for the regime circuit breaker service."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.persistent_lockout_service import LockoutState
from services.regime_circuit_breaker_service import CIRCUIT_BREAKER_VERSION, check_circuit_breaker

_TS = "2026-06-01T00:00:00+00:00"


def _normal_state() -> LockoutState:
    return LockoutState(
        version="risk_lockout_state_v1",
        active=False,
        status="normal",
        reason=None,
        updated_at=_TS,
        payload={},
    )


def _locked_state(status: str = "lockout") -> LockoutState:
    return LockoutState(
        version="risk_lockout_state_v1",
        active=True,
        status=status,
        reason="delta_hedge_required",
        updated_at=_TS,
        payload={},
    )


def test_off_mode_always_allows_buy():
    dec = check_circuit_breaker(signal_action="buy", lockout_state=_locked_state(), mode="off")
    assert dec.action == "allow"
    assert dec.runtime_effect == "no_effect_pass_through"


def test_off_mode_always_allows_sell():
    dec = check_circuit_breaker(signal_action="sell", lockout_state=_locked_state(), mode="off")
    assert dec.action == "allow"


def test_sell_always_passes_in_block_mode():
    dec = check_circuit_breaker(signal_action="sell", lockout_state=_locked_state(), mode="block")
    assert dec.action == "allow"
    reasons_str = " ".join(dec.reasons)
    assert "sell_exempt" in reasons_str


def test_action_is_case_normalized():
    dec = check_circuit_breaker(signal_action="BUY", lockout_state=_locked_state(), mode="block")
    assert dec.action == "block"
    reasons_str = " ".join(dec.reasons)
    assert "signal_action=buy" in reasons_str


def test_no_active_lockout_allows_buy_in_any_mode():
    for mode in ("observe", "warn", "block"):
        dec = check_circuit_breaker(signal_action="buy", lockout_state=_normal_state(), mode=mode)
        assert dec.action == "allow", f"expected allow in mode={mode}, got {dec.action}"


def test_observe_mode_allows_but_annotates_would_block():
    dec = check_circuit_breaker(signal_action="buy", lockout_state=_locked_state(), mode="observe")
    assert dec.action == "allow"
    assert "observe" in dec.runtime_effect


def test_warn_mode_returns_warn_action():
    dec = check_circuit_breaker(signal_action="buy", lockout_state=_locked_state(), mode="warn")
    assert dec.action == "warn"
    assert "warn" in dec.runtime_effect


def test_block_mode_blocks_buy_when_lockout_active():
    dec = check_circuit_breaker(signal_action="buy", lockout_state=_locked_state(), mode="block")
    assert dec.action == "block"
    assert dec.runtime_effect == "buy_blocked_by_regime_circuit_breaker"
    assert dec.lockout_active is True


def test_block_mode_with_rebuilding_status_still_blocks():
    dec = check_circuit_breaker(
        signal_action="buy",
        lockout_state=_locked_state(status="rebuilding"),
        mode="block",
    )
    assert dec.action == "block"


def test_unknown_mode_defaults_to_off():
    dec = check_circuit_breaker(signal_action="buy", lockout_state=_locked_state(), mode="unknown_mode")
    assert dec.action == "allow"
    assert dec.mode == "off"


def test_decision_exposes_lockout_metadata():
    locked = _locked_state()
    dec = check_circuit_breaker(signal_action="buy", lockout_state=locked, mode="block")
    assert dec.lockout_status == "lockout"
    assert dec.lockout_reason == "delta_hedge_required"
    assert dec.version == CIRCUIT_BREAKER_VERSION


def test_decision_serializes_to_dict():
    dec = check_circuit_breaker(signal_action="buy", lockout_state=_normal_state(), mode="off")
    d = dec.to_dict()
    assert "action" in d
    assert "mode" in d
    assert "runtime_effect" in d
    assert "reasons" in d


def main():
    tests = [
        test_off_mode_always_allows_buy,
        test_off_mode_always_allows_sell,
        test_sell_always_passes_in_block_mode,
        test_action_is_case_normalized,
        test_no_active_lockout_allows_buy_in_any_mode,
        test_observe_mode_allows_but_annotates_would_block,
        test_warn_mode_returns_warn_action,
        test_block_mode_blocks_buy_when_lockout_active,
        test_block_mode_with_rebuilding_status_still_blocks,
        test_unknown_mode_defaults_to_off,
        test_decision_exposes_lockout_metadata,
        test_decision_serializes_to_dict,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} circuit breaker tests passed.")


if __name__ == "__main__":
    main()
