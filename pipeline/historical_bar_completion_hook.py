#!/usr/bin/env python3
"""Trigger observe-only retraining once historical bar backfill is complete enough."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from pipeline import run_child  # noqa: E402
from trading_bot.ops_checks.commands.historical_bar_progress_checks import (  # noqa: E402
    DEFAULT_MANIFEST_DIR,
    _cache_symbol_progress,
    _load_manifests,
)

DEFAULT_STATE_PATH = Path("runtime_state/historical_bar_training_hook_state.json")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_state(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        return {}
    return {}


def _write_state(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    tmp.replace(path)


def _fingerprint(payload: dict) -> str:
    return hashlib.sha256(
        json.dumps(payload, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def build_completion_assessment(args: argparse.Namespace) -> dict:
    cache_dir = BASE_DIR / DEFAULT_MANIFEST_DIR.parent
    progress = _cache_symbol_progress(
        cache_dir,
        min_days=args.min_days,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    manifests = _load_manifests(BASE_DIR / DEFAULT_MANIFEST_DIR, limit=10)
    errors = [err for manifest in manifests for err in (manifest.get("errors") or [])]
    latest_errors = (manifests[0] or {}).get("errors") or [] if manifests else []
    ready_symbols = sorted(row["symbol"] for row in progress if row.get("ready"))
    remaining_symbols = sorted(row["symbol"] for row in progress if not row.get("ready"))
    readiness = {
        "ready_symbols": ready_symbols,
        "symbols_ready": len(ready_symbols),
        "symbols_remaining": len(remaining_symbols),
        "min_symbols": args.min_symbols,
        "min_days": args.min_days,
        "latest_manifest": (manifests[0] or {}).get("manifest_file") if manifests else None,
        "recent_manifest_errors": len(errors),
        "latest_manifest_errors": len(latest_errors),
    }
    readiness["coverage_hash"] = _fingerprint(readiness)
    ready = len(ready_symbols) >= args.min_symbols and not latest_errors
    return {
        "report_version": "historical_bar_completion_hook_v1",
        "runtime_effect": "candidate_training_trigger_only_no_live_authority",
        "status": "ready" if ready else "not_ready",
        "training_allowed": ready,
        "reason": (
            "historical bar cache coverage crossed configured floor"
            if ready
            else "historical bar cache coverage is not ready or latest manifest has errors"
        ),
        "readiness": readiness,
        "recent_errors": errors,
        "latest_errors": latest_errors,
        "remaining_symbols": remaining_symbols,
    }


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
    print("Running historical-bar completion retraining:")
    print("  " + " ".join(cmd))
    return run_child(cmd, cwd=BASE_DIR)


def _print_payload(payload: dict, *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(f"report_version        : {payload.get('report_version')}")
    print(f"runtime_effect        : {payload.get('runtime_effect')}")
    print(f"status                : {payload.get('status')}")
    print(f"reason                : {payload.get('reason')}")
    readiness = payload.get("readiness") or {}
    print(f"symbols_ready         : {readiness.get('symbols_ready')}")
    print(f"symbols_remaining     : {readiness.get('symbols_remaining')}")
    print(f"min_symbols           : {readiness.get('min_symbols')}")
    print(f"min_days              : {readiness.get('min_days')}")
    print(f"latest_manifest       : {readiness.get('latest_manifest')}")
    print(f"recent_manifest_errors: {readiness.get('recent_manifest_errors')}")
    print(f"latest_manifest_errors: {readiness.get('latest_manifest_errors')}")
    if payload.get("retrain_exit_code") is not None:
        print(f"retrain_exit_code     : {payload.get('retrain_exit_code')}")


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True)
    parser.add_argument("--start-date", default="2024-06-01")
    parser.add_argument("--end-date")
    parser.add_argument("--min-days", type=int, default=252)
    parser.add_argument("--min-symbols", type=int, default=20)
    parser.add_argument("--sessions", type=int, default=5)
    parser.add_argument("--bad-session-limit", type=int, default=3)
    parser.add_argument("--state-path", default=str(DEFAULT_STATE_PATH))
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    payload = build_completion_assessment(args)
    state_path = Path(args.state_path)
    state = _read_state(state_path)
    coverage_hash = (payload.get("readiness") or {}).get("coverage_hash")
    if payload["training_allowed"] and state.get("last_trained_coverage_hash") == coverage_hash:
        payload["status"] = "skipped_already_trained_for_coverage"
        payload["reason"] = "historical bar readiness fingerprint already trained"
        _print_payload(payload, as_json=args.json)
        return 0
    if not payload["training_allowed"] or args.dry_run:
        if not payload["training_allowed"]:
            state.update(
                {
                    "report_version": "historical_bar_training_hook_state_v1",
                    "last_status": payload["status"],
                    "last_readiness": payload.get("readiness"),
                    "updated_at": _now(),
                }
            )
            if not args.dry_run:
                _write_state(state_path, state)
        elif args.dry_run:
            payload["status"] = "would_trigger_retraining"
            payload["reason"] = "historical bar readiness crossed floor; dry run only"
        _print_payload(payload, as_json=args.json)
        return 0

    exit_code = _run_retraining(args)
    payload["retrain_exit_code"] = exit_code
    state.update(
        {
            "report_version": "historical_bar_training_hook_state_v1",
            "last_status": "trained" if exit_code == 0 else "training_failed",
            "last_trained_coverage_hash": coverage_hash
            if exit_code == 0
            else state.get("last_trained_coverage_hash"),
            "last_readiness": payload.get("readiness"),
            "last_retrain_exit_code": exit_code,
            "updated_at": _now(),
        }
    )
    _write_state(state_path, state)
    _print_payload(payload, as_json=args.json)
    return 0 if exit_code == 0 else exit_code


if __name__ == "__main__":
    raise SystemExit(main())
