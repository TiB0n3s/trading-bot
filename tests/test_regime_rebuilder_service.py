#!/usr/bin/env python3
"""Tests for the regime rebuilder (tranche-based re-entry) service."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.persistent_lockout_service import LockoutState, PersistentLockoutService
from services.regime_rebuilder_service import (
    REBUILDER_VERSION,
    DEFAULT_TRANCHE_COUNT,
    advance_tranche,
    compute_tranche_plan,
)

_TS = "2026-06-01T00:00:00+00:00"
_SYMBOLS = ["AAPL", "MSFT", "NVDA", "GOOGL", "META", "AMZN", "TSLA", "SPY"]


def _normal_state() -> LockoutState:
    return LockoutState(
        version="risk_lockout_state_v1",
        active=False,
        status="normal",
        reason=None,
        updated_at=_TS,
        payload={},
    )


def _rebuilding_state(current_tranche: int = 1) -> LockoutState:
    return LockoutState(
        version="risk_lockout_state_v1",
        active=True,
        status="rebuilding",
        reason="begin_tranched_reentry",
        updated_at=_TS,
        payload={"rebuild_state": {"current_tranche": current_tranche, "total_tranches": 4}},
    )


def test_not_rebuilding_returns_not_rebuilding_status():
    plan = compute_tranche_plan(
        lockout_state=_normal_state(),
        available_cash=10_000.0,
        target_symbols=_SYMBOLS,
    )
    assert plan.status == "not_rebuilding"
    assert plan.tranche_cash_allocation == 0.0
    assert plan.symbols_this_tranche == []


def test_first_tranche_deploys_25pct_cash():
    plan = compute_tranche_plan(
        lockout_state=_rebuilding_state(current_tranche=1),
        available_cash=10_000.0,
        target_symbols=_SYMBOLS,
    )
    assert plan.status == "rebuilding"
    assert plan.current_tranche == 1
    assert plan.tranche_cash_allocation == 2_500.0
    assert plan.tranche_pct_of_available == 0.25


def test_tranche_2_covers_more_symbols_than_tranche_1():
    plan1 = compute_tranche_plan(
        lockout_state=_rebuilding_state(current_tranche=1),
        available_cash=10_000.0,
        target_symbols=_SYMBOLS,
    )
    plan2 = compute_tranche_plan(
        lockout_state=_rebuilding_state(current_tranche=2),
        available_cash=10_000.0,
        target_symbols=_SYMBOLS,
    )
    assert len(plan2.symbols_this_tranche) >= len(plan1.symbols_this_tranche)


def test_small_symbol_lists_use_ceil_for_monotonic_coverage():
    plan = compute_tranche_plan(
        lockout_state=_rebuilding_state(current_tranche=1),
        available_cash=10_000.0,
        target_symbols=["AAPL", "MSFT", "NVDA"],
    )
    assert len(plan.symbols_this_tranche) == 1


def test_final_tranche_covers_all_symbols():
    plan = compute_tranche_plan(
        lockout_state=_rebuilding_state(current_tranche=DEFAULT_TRANCHE_COUNT),
        available_cash=10_000.0,
        target_symbols=_SYMBOLS,
    )
    assert plan.symbols_this_tranche == plan.symbols_ranked
    assert len(plan.symbols_this_tranche) == len(_SYMBOLS)


def test_past_last_tranche_returns_complete():
    plan = compute_tranche_plan(
        lockout_state=_rebuilding_state(current_tranche=DEFAULT_TRANCHE_COUNT + 1),
        available_cash=10_000.0,
        target_symbols=_SYMBOLS,
    )
    assert plan.status == "complete"


def test_per_symbol_allocation_is_even():
    plan = compute_tranche_plan(
        lockout_state=_rebuilding_state(current_tranche=4),
        available_cash=10_000.0,
        target_symbols=_SYMBOLS,
    )
    if plan.symbols_this_tranche:
        values = set(plan.per_symbol_allocation.values())
        assert len(values) == 1  # all equal


def test_symbol_scores_affect_ranking():
    scores = {"NVDA": 100.0, "AAPL": 50.0, "MSFT": 10.0}
    plan = compute_tranche_plan(
        lockout_state=_rebuilding_state(current_tranche=1),
        available_cash=10_000.0,
        target_symbols=["AAPL", "MSFT", "NVDA"],
        symbol_scores=scores,
    )
    # NVDA has the highest score, should be first in ranked
    assert plan.symbols_ranked[0] == "NVDA"


def test_runtime_effect_is_always_observe_only():
    for state in [_normal_state(), _rebuilding_state()]:
        plan = compute_tranche_plan(
            lockout_state=state,
            available_cash=5_000.0,
            target_symbols=_SYMBOLS,
        )
        assert plan.runtime_effect == "observe_only_no_order_authority"


def test_advance_tranche_increments_state():
    with tempfile.TemporaryDirectory() as tmpdir:
        lockout_path = Path(tmpdir) / "risk_lockout.json"
        svc = PersistentLockoutService(lockout_path)
        svc.set_rebuilding(
            reason="begin_tranched_reentry",
            payload={"rebuild_state": {"current_tranche": 1, "total_tranches": 4}},
        )

        result = advance_tranche(lockout_path=lockout_path)
        assert result["action"] == "tranche_advanced"
        assert result["from_tranche"] == 1
        assert result["to_tranche"] == 2
        assert result["runtime_effect"] == "observe_only_no_order_authority"


def test_advance_tranche_clears_lockout_after_last():
    with tempfile.TemporaryDirectory() as tmpdir:
        lockout_path = Path(tmpdir) / "risk_lockout.json"
        svc = PersistentLockoutService(lockout_path)
        svc.set_rebuilding(
            reason="begin_tranched_reentry",
            payload={"rebuild_state": {"current_tranche": 4, "total_tranches": 4}},
        )

        result = advance_tranche(lockout_path=lockout_path)
        assert result["action"] == "rebuild_complete"
        assert result["lockout_state"]["active"] is False
        assert result["lockout_state"]["status"] == "normal"


def test_advance_tranche_can_require_execution_confirmation():
    with tempfile.TemporaryDirectory() as tmpdir:
        lockout_path = Path(tmpdir) / "risk_lockout.json"
        svc = PersistentLockoutService(lockout_path)
        svc.set_rebuilding(
            reason="begin_tranched_reentry",
            payload={"rebuild_state": {"current_tranche": 1, "total_tranches": 4}},
        )

        result = advance_tranche(lockout_path=lockout_path, execution_confirmed=False)
        assert result["action"] == "confirmation_required"
        assert PersistentLockoutService(lockout_path).read().payload["rebuild_state"]["current_tranche"] == 1


def test_advance_tranche_no_op_when_not_rebuilding():
    with tempfile.TemporaryDirectory() as tmpdir:
        lockout_path = Path(tmpdir) / "risk_lockout.json"
        # File does not exist → state reads as normal
        result = advance_tranche(lockout_path=lockout_path)
        assert result["action"] == "no_op"


def test_plan_serializes_to_dict():
    plan = compute_tranche_plan(
        lockout_state=_rebuilding_state(current_tranche=2),
        available_cash=8_000.0,
        target_symbols=_SYMBOLS,
    )
    d = plan.to_dict()
    assert "current_tranche" in d
    assert "symbols_ranked" in d
    assert "per_symbol_allocation" in d
    assert "runtime_effect" in d
    assert d["version"] == REBUILDER_VERSION


def main():
    tests = [
        test_not_rebuilding_returns_not_rebuilding_status,
        test_first_tranche_deploys_25pct_cash,
        test_tranche_2_covers_more_symbols_than_tranche_1,
        test_small_symbol_lists_use_ceil_for_monotonic_coverage,
        test_final_tranche_covers_all_symbols,
        test_past_last_tranche_returns_complete,
        test_per_symbol_allocation_is_even,
        test_symbol_scores_affect_ranking,
        test_runtime_effect_is_always_observe_only,
        test_advance_tranche_increments_state,
        test_advance_tranche_clears_lockout_after_last,
        test_advance_tranche_can_require_execution_confirmation,
        test_advance_tranche_no_op_when_not_rebuilding,
        test_plan_serializes_to_dict,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} regime rebuilder tests passed.")


if __name__ == "__main__":
    main()
