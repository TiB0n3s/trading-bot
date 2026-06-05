#!/usr/bin/env python3
"""Trigger observe-only ML retraining when the approved symbol universe changes."""

from __future__ import annotations

import argparse
import json
from pathlib import Path
import subprocess
import sys

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from db import DB_PATH
from services.symbol_universe_retraining_service import (
    DEFAULT_MIN_BAR_DAYS,
    DEFAULT_MIN_BAR_ROWS,
    DEFAULT_STATE_PATH,
    SymbolUniverseRetrainingService,
)


def _print_human(payload: dict) -> None:
    print(f"report_version       : {payload.get('report_version')}")
    print(f"runtime_effect       : {payload.get('runtime_effect')}")
    print(f"status               : {payload.get('status')}")
    print(f"reason               : {payload.get('reason')}")
    print(f"retraining_required  : {payload.get('retraining_required')}")
    print(f"retraining_allowed   : {payload.get('retraining_allowed')}")
    current = payload.get("current_snapshot") or {}
    previous = payload.get("previous_snapshot") or {}
    print(f"current_version      : {current.get('symbol_universe_version')}")
    print(f"current_symbols      : {current.get('symbol_count')}")
    if previous:
        print(f"previous_symbols     : {previous.get('symbol_count')}")
    if payload.get("added_symbols"):
        print(f"added_symbols        : {', '.join(payload['added_symbols'])}")
    if payload.get("removed_symbols"):
        print(f"removed_symbols      : {', '.join(payload['removed_symbols'])}")
    if payload.get("blockers"):
        print("blockers:")
        for blocker in payload["blockers"]:
            print(f"  - {blocker}")
    coverage = payload.get("coverage") or {}
    if coverage:
        print("coverage:")
        for symbol, row in coverage.items():
            print(
                f"  {symbol:<6} rows={int(row.get('rows') or 0):>7} "
                f"days={int(row.get('trading_days') or 0):>4} "
                f"status={row.get('coverage_status')}"
            )
    if payload.get("retrain_exit_code") is not None:
        print(f"retrain_exit_code    : {payload.get('retrain_exit_code')}")


def _run_retraining(args: argparse.Namespace) -> int:
    cmd = [
        sys.executable,
        str(BASE_DIR / "pipeline" / "retrain.py"),
        "--date",
        args.date,
        "--sessions",
        str(args.sessions),
        "--bad-session-limit",
        str(args.bad_session_limit),
        "--force",
        "--rerun-completed",
    ]
    if args.artifact_dir:
        cmd.extend(["--artifact-dir", args.artifact_dir])
    if args.db_path:
        cmd.extend(["--db-path", args.db_path])
    print("Running universe-change retraining:")
    print("  " + " ".join(cmd))
    result = subprocess.run(cmd, cwd=BASE_DIR)
    return int(result.returncode)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--db-path", default=str(DB_PATH))
    parser.add_argument("--state-path", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--min-bar-rows", type=int, default=DEFAULT_MIN_BAR_ROWS)
    parser.add_argument("--min-bar-days", type=int, default=DEFAULT_MIN_BAR_DAYS)
    parser.add_argument("--sessions", type=int, default=5)
    parser.add_argument("--bad-session-limit", type=int, default=3)
    parser.add_argument("--artifact-dir")
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    service = SymbolUniverseRetrainingService(
        state_path=args.state_path,
        db_path=args.db_path,
    )
    assessment = service.assess(
        min_bar_rows=args.min_bar_rows,
        min_bar_days=args.min_bar_days,
    )
    payload = assessment.to_dict()

    if assessment.status == "needs_baseline":
        if not args.dry_run:
            service.initialize_baseline()
        payload["status"] = "baseline_initialized" if not args.dry_run else "baseline_needed"
        payload["reason"] = (
            "initialized current approved-symbol universe baseline"
            if not args.dry_run
            else assessment.reason
        )
        payload["state_path"] = str(args.state_path)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            _print_human(payload)
        return 0

    if assessment.retraining_required and not assessment.retraining_allowed:
        if not args.dry_run:
            service.record_pending(assessment)
        payload["state_path"] = str(args.state_path)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            _print_human(payload)
        return 0

    if not assessment.retraining_required:
        payload["state_path"] = str(args.state_path)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            _print_human(payload)
        return 0

    if args.dry_run:
        payload["status"] = "would_trigger_retraining"
        payload["state_path"] = str(args.state_path)
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            _print_human(payload)
        return 0

    exit_code = _run_retraining(args)
    payload["retrain_exit_code"] = exit_code
    if exit_code == 0:
        service.record_trained(assessment, retrain_exit_code=exit_code)
        payload["status"] = "retraining_completed"
        payload["reason"] = "universe-change retraining completed; no live authority changed"
    else:
        service.record_pending(assessment)
        payload["status"] = "retraining_failed_pending_retry"
        payload["reason"] = "universe-change retraining failed; pending state will retry next run"

    payload["state_path"] = str(args.state_path)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        _print_human(payload)
    return 0 if exit_code == 0 else exit_code


if __name__ == "__main__":
    raise SystemExit(main())
