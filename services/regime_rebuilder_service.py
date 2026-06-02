"""Tranche-based portfolio rebuilder for regime recovery.

After a crash-regime lockout is resolved and State-0 stability is confirmed,
this service computes 4 time-weighted tranches to incrementally redeploy
available cash back into target equity positions.

Recovery flow
-------------
  lockout (State 2 confirmed)
    → reentry_protocol triggers begin_tranched_reentry
    → cover SPY short (operator step, not this module)
    → advance through tranche 1 → 2 → 3 → 4
    → lock clears after tranche 4 executes

Tranche sizing
--------------
Each tranche deploys an equal fraction (1 / total_tranches = 25%) of
available cash. Symbol coverage grows per tranche so early tranches are
concentrated in the highest-ranked names and later tranches broaden out:

  Tranche 1: top 25% of ranked symbols
  Tranche 2: top 50% of ranked symbols
  Tranche 3: top 75% of ranked symbols
  Tranche 4: all ranked symbols

This module emits allocation plans only. It does not place orders, call the
broker, or modify position sizes directly.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import math
from pathlib import Path
from typing import Any

from services.persistent_lockout_service import LockoutState, PersistentLockoutService

REBUILDER_VERSION = "regime_rebuilder_v1"
DEFAULT_TRANCHE_COUNT = 4


@dataclass(frozen=True)
class TrancheAllocationPlan:
    version: str
    status: str                          # "rebuilding" | "complete" | "not_rebuilding"
    current_tranche: int                 # 1-4; 0 = not started / not applicable
    total_tranches: int
    tranche_cash_allocation: float       # cash to deploy this tranche
    tranche_pct_of_available: float      # fraction of total available cash (e.g. 0.25)
    symbols_ranked: list[str]            # all eligible symbols in priority order
    symbols_this_tranche: list[str]      # subset to target this tranche
    per_symbol_allocation: dict[str, float]  # symbol → cash amount
    runtime_effect: str
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _tranche_from_payload(payload: dict[str, Any]) -> int:
    rebuild = payload.get("rebuild_state") or {}
    return int(rebuild.get("current_tranche", 0))


def _update_payload_tranche(
    payload: dict[str, Any],
    new_tranche: int,
    total_tranches: int,
) -> dict[str, Any]:
    rebuild = dict(payload.get("rebuild_state") or {})
    rebuild["current_tranche"] = new_tranche
    rebuild["total_tranches"] = total_tranches
    rebuild["updated_at"] = datetime.now(timezone.utc).isoformat()
    return {**payload, "rebuild_state": rebuild}


def compute_tranche_plan(
    *,
    lockout_state: LockoutState,
    available_cash: float,
    target_symbols: list[str],
    symbol_scores: dict[str, float] | None = None,
    total_tranches: int = DEFAULT_TRANCHE_COUNT,
) -> TrancheAllocationPlan:
    """Compute the current tranche allocation plan.

    Parameters
    ----------
    lockout_state : LockoutState
        Must be in ``status="rebuilding"`` for a non-trivial plan.
    available_cash : float
        Total current deployable cash. The current tranche receives
        ``1 / total_tranches`` of this amount.
    target_symbols : list[str]
        All symbols eligible for re-entry (e.g. from symbols_config.py).
    symbol_scores : dict[str, float] | None
        Optional per-symbol priority scores; higher = deployed sooner.
    total_tranches : int
        Number of tranches (default 4).
    """
    if not lockout_state.active or lockout_state.status != "rebuilding":
        return TrancheAllocationPlan(
            version=REBUILDER_VERSION,
            status="not_rebuilding",
            current_tranche=0,
            total_tranches=total_tranches,
            tranche_cash_allocation=0.0,
            tranche_pct_of_available=0.0,
            symbols_ranked=[],
            symbols_this_tranche=[],
            per_symbol_allocation={},
            runtime_effect="observe_only_no_order_authority",
            reasons=["lockout_status_not_rebuilding"],
        )

    payload = lockout_state.payload or {}
    current_tranche = _tranche_from_payload(payload) or 1

    if current_tranche > total_tranches:
        return TrancheAllocationPlan(
            version=REBUILDER_VERSION,
            status="complete",
            current_tranche=current_tranche,
            total_tranches=total_tranches,
            tranche_cash_allocation=0.0,
            tranche_pct_of_available=0.0,
            symbols_ranked=[],
            symbols_this_tranche=[],
            per_symbol_allocation={},
            runtime_effect="observe_only_no_order_authority",
            reasons=["all_tranches_complete"],
        )

    scores = symbol_scores or {}
    ranked = sorted(target_symbols, key=lambda s: scores.get(s, 0.0), reverse=True)

    tranche_pct = 1.0 / total_tranches
    tranche_cash = round(available_cash * tranche_pct, 2)

    # Coverage grows linearly: tranche K covers top K/N of ranked symbols.
    symbol_count = max(1, math.ceil(len(ranked) * current_tranche / total_tranches))
    this_tranche = ranked[:symbol_count]

    per_sym = round(tranche_cash / len(this_tranche), 2) if this_tranche else 0.0
    per_symbol_alloc = {sym: per_sym for sym in this_tranche}

    return TrancheAllocationPlan(
        version=REBUILDER_VERSION,
        status="rebuilding",
        current_tranche=current_tranche,
        total_tranches=total_tranches,
        tranche_cash_allocation=tranche_cash,
        tranche_pct_of_available=round(tranche_pct, 4),
        symbols_ranked=ranked,
        symbols_this_tranche=this_tranche,
        per_symbol_allocation=per_symbol_alloc,
        runtime_effect="observe_only_no_order_authority",
        reasons=[
            f"tranche={current_tranche}_of_{total_tranches}",
            f"available_cash={available_cash:.2f}",
            f"tranche_cash={tranche_cash:.2f}",
            f"symbols_this_tranche={len(this_tranche)}",
            f"per_symbol_allocation={per_sym:.2f}",
        ],
    )


def advance_tranche(
    *,
    lockout_path: Path | str,
    total_tranches: int = DEFAULT_TRANCHE_COUNT,
    execution_confirmed: bool = True,
) -> dict[str, Any]:
    """Mark the current tranche complete and advance to the next.

    Clears the lockout when all tranches are exhausted.

    This function writes to the lockout state file. It does not place orders.
    Callers should set ``execution_confirmed=False`` until the previous
    tranche's orders/fills have been confirmed.
    """
    service = PersistentLockoutService(lockout_path)
    state = service.read()

    if not state.active or state.status != "rebuilding":
        return {
            "action": "no_op",
            "reason": "not_in_rebuilding_status",
            "lockout_state": state.to_dict(),
            "runtime_effect": "observe_only_no_order_authority",
        }

    payload = state.payload or {}
    current_tranche = _tranche_from_payload(payload) or 1
    next_tranche = current_tranche + 1

    if not execution_confirmed:
        return {
            "action": "confirmation_required",
            "from_tranche": current_tranche,
            "total_tranches": total_tranches,
            "reason": "tranche execution/fills not confirmed",
            "lockout_state": state.to_dict(),
            "runtime_effect": "observe_only_no_order_authority",
        }

    if next_tranche > total_tranches:
        cleared = service.clear(reason="rebuild_complete_all_tranches_executed")
        return {
            "action": "rebuild_complete",
            "from_tranche": current_tranche,
            "total_tranches": total_tranches,
            "lockout_state": cleared.to_dict(),
            "runtime_effect": "observe_only_no_order_authority",
        }

    new_payload = _update_payload_tranche(payload, next_tranche, total_tranches)
    new_state = service.set_rebuilding(
        reason=f"tranche_{current_tranche}_complete_advancing_to_{next_tranche}",
        payload=new_payload,
    )
    return {
        "action": "tranche_advanced",
        "from_tranche": current_tranche,
        "to_tranche": next_tranche,
        "total_tranches": total_tranches,
        "lockout_state": new_state.to_dict(),
        "runtime_effect": "observe_only_no_order_authority",
    }
