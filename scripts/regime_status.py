#!/usr/bin/env python3
"""Operator command: show current market regime, HMM state, routing, and lockout status.

Usage:
  python3 regime_status.py
  python3 regime_status.py --json
  python3 regime_status.py --closes 100
  python3 regime_status.py --artifact ml/models/regime_hmm_v1/model.joblib
  python3 regime_status.py --routing-matrix
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from symbols_config import APPROVED_SYMBOLS_LIST

from repositories.regime_repo import fetch_spy_closes
from services.persistent_lockout_service import PersistentLockoutService
from services.regime_model_router_service import route_to_model, routing_matrix_summary
from services.regime_rebuilder_service import compute_tranche_plan
from services.regime_risk_protocol_service import crash_risk_protocol, reentry_protocol
from services.regime_switching_service import (
    detect_regime,
    infer_regime_from_artifact,
    load_regime_state,
    save_regime_state,
)

BASE_DIR = Path(__file__).resolve().parent
DEFAULT_ARTIFACT = BASE_DIR / "ml" / "models" / "regime_hmm_v1" / "model.joblib"
DEFAULT_STATE = BASE_DIR / "runtime_state" / "regime_state.json"
DEFAULT_LOCKOUT = BASE_DIR / "runtime_state" / "risk_lockout.json"


def _stability_counter(history: list[int], target_regime: int = 0, window: int = 5) -> int:
    return sum(1 for r in history[-window:] if r == target_regime)


def main() -> int:
    parser = argparse.ArgumentParser(description="Market regime status report")
    parser.add_argument(
        "--closes",
        type=int,
        default=60,
        metavar="N",
        help="Number of SPY closes to pull from feature_snapshots (default 60)",
    )
    parser.add_argument(
        "--artifact", default=str(DEFAULT_ARTIFACT), help="Path to trained HMM joblib artifact"
    )
    parser.add_argument(
        "--state", default=str(DEFAULT_STATE), help="Path to persisted regime history JSON"
    )
    parser.add_argument(
        "--lockout-path", default=str(DEFAULT_LOCKOUT), help="Path to persistent lockout JSON"
    )
    parser.add_argument(
        "--available-cash", type=float, default=0.0, help="Available cash for tranche plan preview"
    )
    parser.add_argument(
        "--routing-matrix", action="store_true", help="Print the full routing matrix and exit"
    )
    parser.add_argument(
        "--json", action="store_true", help="Output raw JSON instead of formatted text"
    )
    parser.add_argument(
        "--no-save", action="store_true", help="Do not persist the inferred regime observation"
    )
    args = parser.parse_args()

    if args.routing_matrix:
        print(json.dumps(routing_matrix_summary(), indent=2, sort_keys=True))
        return 0

    closes = fetch_spy_closes(args.closes)
    state = load_regime_state(args.state)
    history: list[int] = state.get("history", [])

    lockout_svc = PersistentLockoutService(args.lockout_path)
    lockout_state = lockout_svc.read()

    artifact_path = Path(args.artifact)
    if artifact_path.exists():
        obs = infer_regime_from_artifact(
            closes=closes, artifact_path=artifact_path, regime_history=history
        )
        source = "hmm_artifact"
    else:
        obs = detect_regime(closes=closes, regime_history=history)
        source = "deterministic_fallback"

    if not args.no_save:
        save_regime_state(args.state, obs)

    routing = route_to_model(obs)

    extended_history = history + ([obs.regime_id] if obs.regime_id is not None else [])
    crash = crash_risk_protocol(
        regime_history=extended_history, lockout_active=lockout_state.active
    )

    stability = _stability_counter(extended_history)
    reentry = reentry_protocol(
        current_regime=obs.regime_id,
        stability_counter=stability,
        current_status=lockout_state.status,
    )

    tranche_plan = compute_tranche_plan(
        lockout_state=lockout_state,
        available_cash=args.available_cash,
        target_symbols=list(APPROVED_SYMBOLS_LIST),
    )

    output = {
        "regime": obs.to_dict(),
        "source": source,
        "artifact_exists": artifact_path.exists(),
        "closes_available": len(closes),
        "routing": routing.to_dict(),
        "crash_protocol": crash.to_dict(),
        "reentry_protocol": reentry.to_dict(),
        "stability_counter": stability,
        "lockout": lockout_state.to_dict(),
        "tranche_plan": tranche_plan.to_dict(),
        "history_tail": history[-10:],
    }

    if args.json:
        print(json.dumps(output, indent=2, sort_keys=True))
        return 0

    _print_report(output, closes)
    return 0


def _print_report(out: dict, closes: list[float]) -> None:
    obs = out["regime"]
    routing = out["routing"]
    crash = out["crash_protocol"]
    reentry = out["reentry_protocol"]
    lock = out["lockout"]
    tranche = out["tranche_plan"]

    sep = "=" * 64
    print(f"\n{sep}")
    print("  Market Regime Status")
    print(sep)
    print(f"  source         : {out['source']} (artifact_exists={out['artifact_exists']})")
    print(f"  closes_used    : {out['closes_available']}")
    print()
    print(f"  regime_id      : {obs['regime_id']}")
    print(f"  regime_label   : {obs['regime_label']}")
    print(f"  stable         : {obs['stable']}")
    print(f"  confidence     : {obs['confidence']}")
    print(f"  recommended    : {obs['recommended_strategy']}")
    print(f"  avg_return_pct : {obs['average_return_pct']}")
    print(f"  volatility_pct : {obs['volatility_pct']}")
    print(f"  history_tail   : {out['history_tail']}")
    print()
    print("  [Sub-model Routing]")
    print(f"  model_slot     : {routing['active_model_slot']}")
    print(f"  sub_model      : {routing['sub_model_strategy']}")
    print(f"  scoring_bias   : {routing['scoring_bias']}")
    print(f"  size_modifier  : {routing['size_modifier']}")
    print(f"  allow_longs    : {routing['allow_new_longs']}")
    print(f"  allow_shorts   : {routing['allow_new_shorts']}")
    print(f"  signal_filter  : {routing['signal_filter']}")
    print()
    print("  [Risk Protocols]")
    print(f"  crash_protocol : {crash['action']}  [{crash['severity']}]")
    print(f"  reentry        : {reentry['action']}  [{reentry['severity']}]")
    print(f"  stability_ctr  : {out['stability_counter']}")
    print()
    print("  [Lockout State]")
    print(f"  active         : {lock['active']}")
    print(f"  status         : {lock['status']}")
    print(f"  reason         : {lock['reason']}")
    print(f"  updated_at     : {lock['updated_at']}")
    print()
    print("  [Tranche Plan]")
    print(f"  status         : {tranche['status']}")
    print(f"  tranche        : {tranche['current_tranche']} / {tranche['total_tranches']}")
    print(f"  tranche_cash   : {tranche['tranche_cash_allocation']:.2f}")
    print(f"  symbols        : {len(tranche['symbols_this_tranche'])}")
    print(sep)


if __name__ == "__main__":
    raise SystemExit(main())
