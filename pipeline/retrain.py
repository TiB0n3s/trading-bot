#!/usr/bin/env python3
"""Automated retraining trigger for observe-only ML artifacts.

The command can train and register a candidate model artifact, but it never
loads models into runtime or changes live trading authority.
"""

from __future__ import annotations

import argparse
from contextlib import contextmanager
import fcntl
import json
import signal
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from ml_platform.config import DEFAULT_DB_PATH, FEATURE_VERSION, MODEL_ROOT
from ml_platform.datasets import dataset_profile
from ml_platform.governance import build_dataset_manifest
from ml_platform.promotion import assess_candidate_promotion, register_candidate_model
from ml_platform.readiness import retraining_readiness_report
from services.prediction_drift_service import build_default_prediction_drift_service
from services.supervised_prediction_training_service import (
    fetch_training_rows,
    train_supervised_prediction_model,
)

DEFAULT_LOCK_FILE = "/tmp/tradingbot_ml_retrain.lock"
DEFAULT_MAX_RUNTIME_SECONDS = 1800


class RetrainingTimeout(Exception):
    pass


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


@contextmanager
def _nonblocking_lock(lock_file: str | None):
    if not lock_file:
        yield True
        return
    path = Path(lock_file)
    path.parent.mkdir(parents=True, exist_ok=True)
    handle = path.open("w")
    acquired = False
    try:
        try:
            fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            acquired = True
        except BlockingIOError:
            yield False
            return
        yield True
    finally:
        if acquired:
            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        handle.close()


def _timeout_handler(signum, frame):  # noqa: ARG001
    raise RetrainingTimeout("automated retraining exceeded max runtime")


def _print_payload(payload: dict[str, Any], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    print(payload.get("reason") or payload.get("status") or "automated retraining result")


def _execute_retraining(args: argparse.Namespace) -> int:
    drift_service = build_default_prediction_drift_service(db_path=args.db_path)
    validation = drift_service.correlation_report(
        target_date=args.target_date or args.end_date,
        sessions=args.sessions,
        threshold=args.threshold,
        bad_session_limit=args.bad_session_limit,
        min_pairs_per_session=args.min_pairs,
    ).to_dict()

    if not args.force and not validation["retraining_recommended"]:
        payload = {
            "report_version": "automated_retraining_v1",
            "runtime_effect": "none",
            "status": "skipped",
            "reason": "prediction validation does not recommend retraining",
            "validation": validation,
        }
        _print_payload(payload, as_json=args.json)
        return 0

    rows = fetch_training_rows(db_path=args.db_path, limit=args.limit)
    stamp = _utc_stamp()
    model_id = f"supervised_prediction_{args.horizon}_{stamp}"
    artifact_dir = Path(args.artifact_dir)
    artifact_path = artifact_dir / f"{model_id}.joblib"
    training = train_supervised_prediction_model(
        rows=rows,
        horizon=args.horizon,
        min_samples=args.min_samples,
        artifact_path=artifact_path,
    ).to_dict()

    profile = dataset_profile(
        db_path=args.db_path,
        start_date=args.start_date,
        end_date=args.end_date,
    )
    manifest = build_dataset_manifest(
        db_path=args.db_path,
        start_date=args.start_date,
        end_date=args.end_date,
        query_version="automated_retraining_v1",
    )
    readiness = retraining_readiness_report(
        dataset_profile=profile,
        dataset_manifest=manifest,
        trading_sessions_observed=args.trading_sessions_observed,
    )
    assessment = assess_candidate_promotion(
        readiness_report=readiness,
        validation_report=validation,
        requested_status=args.requested_status,
        explicit_operator_approval=args.operator_approved,
    )
    metrics_path = artifact_dir / f"{model_id}.metrics.json"
    metrics = {
        "report_version": "automated_retraining_metrics_v1",
        "validation": validation,
        "training": training,
        "readiness": readiness,
        "promotion_assessment": assessment.to_dict(),
    }
    _write_json(metrics_path, metrics)

    registry_entry = None
    if training.get("trained") and training.get("artifact_path") and assessment.allowed:
        registry_entry = register_candidate_model(
            assessment=assessment,
            model_id=model_id,
            artifact_path=str(training["artifact_path"]),
            metrics_path=str(metrics_path),
            feature_version=FEATURE_VERSION,
            target=f"ret_fwd_{args.horizon}",
            training_window=f"{args.start_date or 'open'}..{args.end_date or args.target_date or 'latest'}",
            validation_window=f"last_{args.sessions}_prediction_sessions",
        )

    payload = {
        "report_version": "automated_retraining_v1",
        "runtime_effect": "candidate_artifact_only_no_live_authority",
        "status": "completed" if registry_entry else "trained_without_registry_promotion",
        "model_id": model_id,
        "metrics_path": str(metrics_path),
        "validation": validation,
        "training": training,
        "readiness": readiness,
        "promotion_assessment": assessment.to_dict(),
        "registry_entry": registry_entry,
    }
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"Automated retraining status: {payload['status']}")
        print(f"Model id: {model_id}")
        print(f"Training: trained={training.get('trained')} samples={training.get('sample_size')}")
        print(f"Promotion allowed: {assessment.allowed}")
        if assessment.blockers:
            print("Promotion blockers:")
            for blocker in assessment.blockers:
                print(f"  - {blocker}")
        print(f"Metrics: {metrics_path}")
    return 0 if training.get("trained") else 1


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", dest="target_date")
    parser.add_argument("--start-date")
    parser.add_argument("--end-date")
    parser.add_argument("--sessions", type=int, default=5)
    parser.add_argument("--threshold", type=float, default=0.0)
    parser.add_argument("--bad-session-limit", type=int, default=3)
    parser.add_argument("--min-pairs", type=int, default=3)
    parser.add_argument("--trading-sessions-observed", type=int, default=0)
    parser.add_argument("--horizon", default="15m")
    parser.add_argument("--min-samples", type=int, default=40)
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument(
        "--artifact-dir",
        default=str(MODEL_ROOT / "supervised_entry_v1" / "candidates"),
    )
    parser.add_argument("--requested-status", default="candidate")
    parser.add_argument("--operator-approved", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--json", action="store_true")
    parser.add_argument(
        "--lock-file",
        default=DEFAULT_LOCK_FILE,
        help="Nonblocking lock file. Use empty string to disable.",
    )
    parser.add_argument(
        "--max-runtime-seconds",
        type=int,
        default=DEFAULT_MAX_RUNTIME_SECONDS,
        help="Abort retraining if it exceeds this many seconds. Use 0 to disable.",
    )
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    lock_file = args.lock_file or None
    with _nonblocking_lock(lock_file) as acquired:
        if not acquired:
            payload = {
                "report_version": "automated_retraining_v1",
                "runtime_effect": "none",
                "status": "skipped_lock_busy",
                "reason": f"another retraining process holds {lock_file}",
            }
            _print_payload(payload, as_json=args.json)
            return 0
        previous_handler = None
        if args.max_runtime_seconds and args.max_runtime_seconds > 0:
            previous_handler = signal.signal(signal.SIGALRM, _timeout_handler)
            signal.alarm(args.max_runtime_seconds)
        try:
            return _execute_retraining(args)
        except RetrainingTimeout as exc:
            payload = {
                "report_version": "automated_retraining_v1",
                "runtime_effect": "none",
                "status": "timeout",
                "reason": str(exc),
                "max_runtime_seconds": args.max_runtime_seconds,
            }
            _print_payload(payload, as_json=args.json)
            return 124
        finally:
            if args.max_runtime_seconds and args.max_runtime_seconds > 0:
                signal.alarm(0)
                if previous_handler is not None:
                    signal.signal(signal.SIGALRM, previous_handler)


if __name__ == "__main__":
    raise SystemExit(main())
