#!/usr/bin/env python3
"""Manage the persistent risk lockout file."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.persistent_lockout_service import PersistentLockoutService
from services.regime_risk_protocol_service import (
    apply_protocol_lockout_state,
    crash_risk_protocol,
    reentry_protocol,
)

DEFAULT_PATH = Path(__file__).resolve().parent / "runtime_state" / "risk_lockout.json"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "action",
        choices=("status", "activate", "rebuilding", "clear", "crash-check", "reentry-check"),
    )
    parser.add_argument("--reason", default="operator_request")
    parser.add_argument("--path", default=str(DEFAULT_PATH))
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--regimes", default="", help="Comma-separated recent regime ids")
    parser.add_argument("--current-regime", type=int)
    parser.add_argument("--stability-counter", type=int, default=0)
    args = parser.parse_args()

    service = PersistentLockoutService(args.path)
    if args.action == "activate":
        state = service.activate(reason=args.reason)
    elif args.action == "rebuilding":
        state = service.set_rebuilding(reason=args.reason)
    elif args.action == "clear":
        state = service.clear(reason=args.reason)
    elif args.action == "crash-check":
        regimes = [int(item) for item in args.regimes.split(",") if item.strip()]
        decision = crash_risk_protocol(
            regime_history=regimes,
            lockout_active=service.read().active,
        )
        data = apply_protocol_lockout_state(decision=decision, lockout_path=args.path)
        if args.json:
            print(json.dumps(data, indent=2, sort_keys=True))
        else:
            print(f"decision  : {data['decision_action']}")
            print(f"active    : {data['lockout_state']['active']}")
            print(f"status    : {data['lockout_state']['status']}")
        return 0
    elif args.action == "reentry-check":
        current = service.read()
        decision = reentry_protocol(
            current_regime=args.current_regime,
            stability_counter=args.stability_counter,
            current_status=current.status,
        )
        data = apply_protocol_lockout_state(decision=decision, lockout_path=args.path)
        if args.json:
            print(json.dumps(data, indent=2, sort_keys=True))
        else:
            print(f"decision  : {data['decision_action']}")
            print(f"active    : {data['lockout_state']['active']}")
            print(f"status    : {data['lockout_state']['status']}")
        return 0
    else:
        state = service.read()

    data = state.to_dict()
    if args.json:
        print(json.dumps(data, indent=2, sort_keys=True))
    else:
        print(f"active    : {data['active']}")
        print(f"status    : {data['status']}")
        print(f"reason    : {data['reason']}")
        print(f"updated_at: {data['updated_at']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
