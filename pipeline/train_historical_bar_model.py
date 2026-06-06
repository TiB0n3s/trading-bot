#!/usr/bin/env python3
"""Train observe-only models directly from historical bar pattern features."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent.parent
if str(BASE_DIR) not in sys.path:
    sys.path.insert(0, str(BASE_DIR))

from ml_platform.config import DEFAULT_DB_PATH, MODEL_ROOT
from repositories.historical_bar_training_repo import (
    fetch_historical_bar_training_rows,
)
from services.supervised_prediction_training_service import (
    ADVANCED_ALPHA_FEATURE_COLUMNS,
    CANDLE_PHYSICS_FEATURE_COLUMNS,
    EXECUTION_MICROSTRUCTURE_FEATURE_COLUMNS,
    train_quant_model_suite,
    train_supervised_prediction_model,
)


HISTORICAL_BAR_TRAINING_VERSION = "historical_bar_observe_training_v1"
DEFAULT_FEATURE_COLUMNS = (
    CANDLE_PHYSICS_FEATURE_COLUMNS
    + ADVANCED_ALPHA_FEATURE_COLUMNS
    + EXECUTION_MICROSTRUCTURE_FEATURE_COLUMNS
)


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


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


def _write_json(path: Path, payload: dict[str, Any]) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _label_counts(rows: list[dict[str, Any]], label_target: str) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        value = row.get(label_target)
        key = "null" if value is None else str(int(float(value)))
        counts[key] = counts.get(key, 0) + 1
    return dict(sorted(counts.items()))


def _baseline_training(
    *,
    rows: list[dict[str, Any]],
    label_target: str,
    artifact_path: Path,
) -> dict[str, Any]:
    labels = []
    for row in rows:
        value = row.get(label_target)
        if value is None:
            continue
        labels.append(int(float(value)))
    split = max(1, int(len(labels) * 0.8))
    train_labels = labels[:split]
    test_labels = labels[split:]
    majority = max(set(train_labels), key=train_labels.count) if train_labels else 0
    accuracy = None
    if test_labels:
        accuracy = round(
            sum(1 for value in test_labels if value == majority) / len(test_labels),
            4,
        )
    positive_rate = None
    if labels:
        positive_rate = round(sum(1 for value in labels if value > 0) / len(labels), 4)
    artifact = {
        "version": "historical_bar_baseline_model_v1",
        "provider": "chronological_majority_baseline",
        "label_target": label_target,
        "majority_label": majority,
        "sample_size": len(labels),
        "accuracy": accuracy,
        "baseline_positive_rate": positive_rate,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "runtime_effect": "observe_only_no_live_authority",
    }
    _write_json(artifact_path.with_suffix(".baseline.json"), artifact)
    return {
        "version": "historical_bar_baseline_model_v1",
        "provider": "chronological_majority_baseline",
        "trained": bool(labels),
        "sample_size": len(labels),
        "feature_columns": [],
        "accuracy": accuracy,
        "baseline_positive_rate": positive_rate,
        "reason": "baseline-only smoke artifact; no live authority",
        "generated_at": artifact["generated_at"],
        "runtime_effect": "observe_only_no_live_authority",
        "dependency_status": {},
        "artifact_path": str(artifact_path.with_suffix(".baseline.json")),
    }


def _run(args: argparse.Namespace) -> dict[str, Any]:
    label_target = args.label_target
    horizon = "triple_barrier" if label_target == "triple_barrier_label" else "trend_scan"
    rows = fetch_historical_bar_training_rows(
        db_path=args.db_path,
        start_date=args.start_date,
        end_date=args.end_date,
        symbol=args.symbol,
        label_target=label_target,
        limit=args.limit,
        rows_per_symbol=args.rows_per_symbol,
    )
    stamp = _stamp()
    model_root = Path(args.artifact_dir)
    model_id = f"historical_bar_{label_target}_{stamp}"
    primary_artifact = model_root / f"{model_id}.joblib"
    if args.baseline_only:
        training = _baseline_training(
            rows=rows,
            label_target=label_target,
            artifact_path=primary_artifact,
        )
    else:
        training = train_supervised_prediction_model(
            rows=rows,
            horizon=horizon,
            feature_columns=list(DEFAULT_FEATURE_COLUMNS),
            min_samples=args.min_samples,
            artifact_path=primary_artifact,
        ).to_dict()
    if args.skip_suite:
        suite = {
            "version": "quant_model_suite_skipped",
            "runtime_effect": "observe_only_no_live_authority",
            "horizon": horizon,
            "sample_size": training.get("sample_size"),
            "feature_columns": list(DEFAULT_FEATURE_COLUMNS),
            "models": [],
            "best_model": None,
            "notes": ["skipped by --skip-suite for fast operator verification"],
        }
    else:
        suite = train_quant_model_suite(
            rows=rows,
            horizon=horizon,
            feature_columns=list(DEFAULT_FEATURE_COLUMNS),
            min_samples=args.min_samples,
            artifact_dir=model_root / "model_suite" / model_id,
            model_id_prefix=model_id,
        ).to_dict()
    diagnostics = {
        "report_version": HISTORICAL_BAR_TRAINING_VERSION,
        "runtime_effect": "observe_only_no_live_authority",
        "model_id": model_id,
        "db_path": str(args.db_path),
        "start_date": args.start_date,
        "end_date": args.end_date,
        "symbol": args.symbol,
        "label_target": label_target,
        "horizon": horizon,
        "rows_loaded": len(rows),
        "rows_per_symbol": args.rows_per_symbol,
        "suite_skipped": args.skip_suite,
        "baseline_only": args.baseline_only,
        "symbols": sorted({str(row.get("symbol")) for row in rows if row.get("symbol")}),
        "symbol_count": len({str(row.get("symbol")) for row in rows if row.get("symbol")}),
        "label_counts": _label_counts(rows, label_target),
        "feature_columns": list(DEFAULT_FEATURE_COLUMNS),
        "training": training,
        "quant_model_suite": suite,
        "git_sha": _git_sha(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "notes": [
            "historical bar model is trained from bar_pattern_features only",
            "artifact is not registered for live authority",
            "runtime decision paths do not read this artifact unless separately wired later",
        ],
    }
    diagnostic_path = model_root / f"{model_id}.diagnostic.json"
    _write_json(diagnostic_path, diagnostics)
    diagnostics["diagnostic_path"] = str(diagnostic_path)
    return diagnostics


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start-date", default="2024-06-01")
    parser.add_argument("--end-date", default="2026-06-04")
    parser.add_argument("--symbol")
    parser.add_argument(
        "--label-target",
        choices=("triple_barrier_label", "trend_scan_label"),
        default="triple_barrier_label",
    )
    parser.add_argument("--limit", type=int, default=50000)
    parser.add_argument(
        "--rows-per-symbol",
        type=int,
        default=1000,
        help=(
            "Balanced current-version rows per symbol before the global limit is "
            "applied. Use 0 to fall back to purely chronological global sampling."
        ),
    )
    parser.add_argument("--min-samples", type=int, default=500)
    parser.add_argument(
        "--skip-suite",
        action="store_true",
        help="Train only the primary model and skip optional comparative suite models.",
    )
    parser.add_argument(
        "--baseline-only",
        action="store_true",
        help="Write a fast chronological majority baseline artifact instead of fitting sklearn.",
    )
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument(
        "--artifact-dir",
        default=str(MODEL_ROOT / "historical_bar_patterns_v1" / "candidates"),
    )
    parser.add_argument("--json", action="store_true")
    return parser.parse_args()


def main() -> int:
    args = _parse_args()
    payload = _run(args)
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"report_version          : {payload['report_version']}")
        print(f"runtime_effect          : {payload['runtime_effect']}")
        print(f"model_id                : {payload['model_id']}")
        print(f"rows_loaded             : {payload['rows_loaded']}")
        print(f"rows_per_symbol         : {payload['rows_per_symbol']}")
        print(f"symbol_count            : {payload['symbol_count']}")
        print(f"label_target            : {payload['label_target']}")
        print(f"label_counts            : {json.dumps(payload['label_counts'], sort_keys=True)}")
        print(
            "training                : "
            f"trained={payload['training'].get('trained')} "
            f"samples={payload['training'].get('sample_size')} "
            f"accuracy={payload['training'].get('accuracy')}"
        )
        best = payload.get("quant_model_suite", {}).get("best_model") or {}
        print(
            "best_suite_model        : "
            f"{best.get('provider') or '-'} accuracy={best.get('accuracy')}"
        )
        print(f"diagnostic_path         : {payload['diagnostic_path']}")
    return 0 if payload.get("training", {}).get("trained") else 1


if __name__ == "__main__":
    raise SystemExit(main())
