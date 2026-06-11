#!/usr/bin/env python3
"""Automated retraining trigger for observe-only ML artifacts.

The command can train and register a candidate model artifact, but it never
loads models into runtime or changes live trading authority.
"""

from __future__ import annotations

import argparse
import fcntl
import json
import os
import platform
import resource
import signal
import subprocess
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from services.prediction_drift_service import (  # noqa: E402
    build_default_prediction_drift_service,
)
from services.retraining_kpi_trigger_service import (  # noqa: E402
    evaluate_retraining_kpi_trigger,
)
from services.supervised_prediction_training_service import (  # noqa: E402
    fetch_training_rows,
    train_quant_model_suite,
    train_supervised_prediction_model,
)

from ml_platform.config import DEFAULT_DB_PATH, FEATURE_VERSION, MODEL_ROOT  # noqa: E402
from ml_platform.datasets import dataset_profile  # noqa: E402
from ml_platform.governance import build_dataset_manifest  # noqa: E402
from ml_platform.promotion import (  # noqa: E402
    assess_candidate_promotion,
    register_candidate_model,
)
from ml_platform.readiness import retraining_readiness_report  # noqa: E402
from ml_platform.registry import prune_model_artifacts  # noqa: E402

DEFAULT_LOCK_FILE = "/tmp/tradingbot_ml_retrain.lock"
DEFAULT_MAX_RUNTIME_SECONDS = 1800
DEFAULT_MEMORY_LIMIT_MB = 4096
DEFAULT_NICE_INCREMENT = 19


class RetrainingTimeout(Exception):
    pass


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n")
    return path


def _git_sha() -> str | None:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=BASE_DIR,
            text=True,
            stderr=subprocess.DEVNULL,
            timeout=2,
        ).strip()
    except Exception:
        return None


def _apply_resource_limits(*, memory_limit_mb: int, nice_increment: int) -> dict[str, Any]:
    result = {
        "runtime_effect": "process_resource_guard",
        "requested_memory_limit_mb": memory_limit_mb,
        "requested_nice_increment": nice_increment,
        "memory_limit_applied": False,
        "nice_applied": False,
        "errors": [],
    }
    if nice_increment > 0:
        try:
            os.nice(int(nice_increment))
            result["nice_applied"] = True
        except Exception as exc:
            result["errors"].append(f"nice_failed:{exc}")
    if memory_limit_mb > 0:
        try:
            bytes_limit = int(memory_limit_mb) * 1024 * 1024
            current_soft, current_hard = resource.getrlimit(resource.RLIMIT_AS)
            hard = bytes_limit
            if current_hard not in (-1, resource.RLIM_INFINITY):
                hard = min(bytes_limit, int(current_hard))
            soft = min(bytes_limit, hard)
            resource.setrlimit(resource.RLIMIT_AS, (soft, hard))
            result["memory_limit_applied"] = True
            result["memory_limit_bytes"] = soft
        except Exception as exc:
            result["errors"].append(f"memory_limit_failed:{exc}")
    return result


def _run_marker_path(artifact_dir: Path, target_date: str | None) -> Path | None:
    if not target_date:
        return None
    safe = str(target_date).replace("/", "-")
    return artifact_dir / "retrain_runs" / f"{safe}.json"


def _completed_marker(path: Path | None) -> dict[str, Any] | None:
    if path is None or not path.exists():
        return None
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    if payload.get("status") in {"completed", "trained_without_registry_promotion"}:
        return payload
    return None


def _default_prediction_time_cutoff(target_date: str | None) -> str:
    if target_date:
        return f"{target_date}T23:59:59+00:00"
    return datetime.now(timezone.utc).isoformat()


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
    artifact_dir = Path(args.artifact_dir)
    target_date = args.target_date or args.end_date
    prediction_time_cutoff = getattr(
        args, "prediction_time_cutoff", None
    ) or _default_prediction_time_cutoff(target_date)
    marker_path = _run_marker_path(artifact_dir, target_date)
    marker = _completed_marker(marker_path)
    if marker and not args.rerun_completed:
        payload = {
            "report_version": "automated_retraining_v1",
            "runtime_effect": "none",
            "status": "skipped_already_completed",
            "reason": f"retraining already completed for {target_date}",
            "target_date": target_date,
            "previous_run": marker,
        }
        _print_payload(payload, as_json=args.json)
        return 0

    resource_guard = _apply_resource_limits(
        memory_limit_mb=args.memory_limit_mb,
        nice_increment=args.nice_increment,
    )
    drift_service = build_default_prediction_drift_service(db_path=args.db_path)
    validation = drift_service.correlation_report(
        target_date=args.target_date or args.end_date,
        sessions=args.sessions,
        threshold=args.threshold,
        bad_session_limit=args.bad_session_limit,
        min_pairs_per_session=args.min_pairs,
    ).to_dict()
    kpi_trigger = evaluate_retraining_kpi_trigger(
        metrics_path=args.kpi_metrics_path,
        min_win_rate=args.min_kpi_win_rate,
        min_sharpe_proxy=args.min_kpi_sharpe_proxy,
        max_drawdown_pct=args.max_kpi_drawdown_pct,
    )
    if kpi_trigger.get("retraining_recommended"):
        validation = dict(validation)
        validation["retraining_recommended"] = True
        validation["kpi_retraining_trigger"] = kpi_trigger

    if not args.force and not validation["retraining_recommended"]:
        payload = {
            "report_version": "automated_retraining_v1",
            "runtime_effect": "none",
            "status": "skipped",
            "reason": "prediction validation does not recommend retraining",
            "validation": validation,
            "kpi_retraining_trigger": kpi_trigger,
        }
        _print_payload(payload, as_json=args.json)
        return 0

    rows = fetch_training_rows(
        db_path=args.db_path,
        limit=args.limit,
        prediction_time_cutoff=prediction_time_cutoff,
    )
    stamp = _utc_stamp()
    model_id = f"supervised_prediction_{args.horizon}_{stamp}"
    artifact_path = artifact_dir / f"{model_id}.joblib"
    training = train_supervised_prediction_model(
        rows=rows,
        horizon=args.horizon,
        min_samples=args.min_samples,
        artifact_path=artifact_path,
    ).to_dict()
    quant_suite = train_quant_model_suite(
        rows=rows,
        horizon=args.horizon,
        min_samples=args.min_samples,
        artifact_dir=artifact_dir / "model_suite" / model_id,
        model_id_prefix=model_id,
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
    diagnostic_path = artifact_path.with_suffix(artifact_path.suffix + ".diagnostic.json")
    pruning = prune_model_artifacts(
        older_than_days=getattr(args, "prune_older_than_days", 30),
        fallback_count=getattr(args, "prune_fallback_count", 3),
    )
    metrics = {
        "report_version": "automated_retraining_metrics_v1",
        "resource_guard": resource_guard,
        "validation": validation,
        "kpi_retraining_trigger": kpi_trigger,
        "training": training,
        "quant_model_suite": quant_suite,
        "readiness": readiness,
        "point_in_time": {
            "feature_available_at_cutoff": prediction_time_cutoff,
            "training_query_guard": "feature_available_at <= cutoff",
        },
        "artifact_pruning": pruning,
        "promotion_assessment": assessment.to_dict(),
    }
    _write_json(metrics_path, metrics)
    diagnostic = {
        "report_version": "automated_retraining_diagnostic_v1",
        "runtime_effect": "diagnostic_only_no_live_authority",
        "model_id": model_id,
        "target_date": target_date,
        "artifact_path": str(training.get("artifact_path") or artifact_path),
        "metrics_path": str(metrics_path),
        "validation_average_correlation": validation.get("average_correlation"),
        "validation_bad_session_count": validation.get("bad_session_count"),
        "validation_valid_session_count": validation.get("valid_session_count"),
        "training_row_count_loaded": len(rows),
        "feature_available_at_cutoff": prediction_time_cutoff,
        "training_sample_size": training.get("sample_size"),
        "training_provider": training.get("provider"),
        "training_accuracy": training.get("accuracy"),
        "quant_suite_best_provider": ((quant_suite.get("best_model") or {}).get("provider")),
        "quant_suite_best_accuracy": ((quant_suite.get("best_model") or {}).get("accuracy")),
        "quant_suite_model_count": len(quant_suite.get("models") or []),
        "python_version": sys.version,
        "platform": platform.platform(),
        "git_sha": _git_sha(),
        "resource_guard": resource_guard,
        "artifact_pruning": {
            "deleted_count": pruning.get("deleted_count"),
            "protected_count": pruning.get("protected_count"),
            "older_than_days": pruning.get("older_than_days"),
        },
        "promotion_allowed": assessment.allowed,
        "promotion_blockers": list(assessment.blockers),
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
    _write_json(diagnostic_path, diagnostic)

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
        "diagnostic_path": str(diagnostic_path),
        "resource_guard": resource_guard,
        "validation": validation,
        "kpi_retraining_trigger": kpi_trigger,
        "training": training,
        "quant_model_suite": quant_suite,
        "readiness": readiness,
        "promotion_assessment": assessment.to_dict(),
        "registry_entry": registry_entry,
    }
    if training.get("trained") and marker_path:
        marker_payload = {
            "report_version": "automated_retraining_run_marker_v1",
            "target_date": target_date,
            "status": payload["status"],
            "model_id": model_id,
            "metrics_path": str(metrics_path),
            "diagnostic_path": str(diagnostic_path),
            "artifact_path": training.get("artifact_path"),
            "registry_entry_written": bool(registry_entry),
            "generated_at": datetime.now(timezone.utc).isoformat(),
        }
        _write_json(marker_path, marker_payload)
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
        print(f"Diagnostic: {diagnostic_path}")
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
    parser.add_argument(
        "--kpi-metrics-path",
        help=(
            "Optional JSON metrics artifact. If win rate, Sharpe proxy, or drawdown "
            "breach thresholds, retraining is recommended even when correlation drift is clean."
        ),
    )
    parser.add_argument("--min-kpi-win-rate", type=float, default=0.48)
    parser.add_argument("--min-kpi-sharpe-proxy", type=float, default=0.0)
    parser.add_argument("--max-kpi-drawdown-pct", type=float, default=-2.0)
    parser.add_argument("--trading-sessions-observed", type=int, default=0)
    parser.add_argument("--horizon", default="15m")
    parser.add_argument("--min-samples", type=int, default=40)
    parser.add_argument("--limit", type=int, default=5000)
    parser.add_argument(
        "--prediction-time-cutoff",
        help=(
            "Point-in-time feature availability cutoff. Defaults to target date "
            "23:59:59 UTC, or now when no target date is supplied."
        ),
    )
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument(
        "--artifact-dir",
        default=str(MODEL_ROOT / "supervised_entry_v1" / "candidates"),
    )
    parser.add_argument("--requested-status", default="candidate")
    parser.add_argument("--operator-approved", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument(
        "--rerun-completed",
        action="store_true",
        help="Allow retraining again even when the target date already has a completed run marker.",
    )
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
    parser.add_argument(
        "--memory-limit-mb",
        type=int,
        default=DEFAULT_MEMORY_LIMIT_MB,
        help="Apply RLIMIT_AS memory cap before training. Use 0 to disable.",
    )
    parser.add_argument(
        "--nice-increment",
        type=int,
        default=DEFAULT_NICE_INCREMENT,
        help="Lower process priority with os.nice before training. Use 0 to disable.",
    )
    parser.add_argument(
        "--prune-older-than-days",
        type=int,
        default=30,
        help="Delete unprotected binary model artifacts older than this many days.",
    )
    parser.add_argument(
        "--prune-fallback-count",
        type=int,
        default=3,
        help="Keep this many recent historical fallback model binaries.",
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
