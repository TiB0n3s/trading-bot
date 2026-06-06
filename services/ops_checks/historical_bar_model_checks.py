"""Operator reports for historical-bar observe-only model candidates."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ml_platform.config import MODEL_ROOT


HISTORICAL_BAR_MODEL_REPORT_VERSION = "historical_bar_model_readiness_v1"
DEFAULT_CANDIDATE_DIR = MODEL_ROOT / "historical_bar_patterns_v1" / "candidates"


@dataclass(frozen=True)
class CandidateAssessment:
    label_target: str
    model_id: str
    rows_loaded: int
    symbol_count: int
    accuracy: float | None
    trained: bool
    runtime_effect: str
    diagnostic_path: str
    status: str
    failed_thresholds: list[str]


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _diagnostics(candidate_dir: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(candidate_dir.glob("historical_bar_*_*.diagnostic.json")):
        payload = _read_json(path)
        if not payload:
            continue
        payload["_diagnostic_path"] = str(path)
        rows.append(payload)
    return rows


def _latest_by_label(rows: list[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for row in rows:
        label = str(row.get("label_target") or "unknown")
        current = latest.get(label)
        if current is None or str(row.get("generated_at") or "") > str(current.get("generated_at") or ""):
            latest[label] = row
    return latest


def _assess(
    row: dict[str, Any],
    *,
    min_rows: int,
    min_symbols: int,
    min_accuracy: float,
) -> CandidateAssessment:
    training = row.get("training") or {}
    rows_loaded = int(row.get("rows_loaded") or 0)
    symbol_count = int(row.get("symbol_count") or 0)
    accuracy = training.get("accuracy")
    if accuracy is not None:
        accuracy = float(accuracy)
    failed: list[str] = []
    if row.get("runtime_effect") != "observe_only_no_live_authority":
        failed.append("runtime_effect_not_observe_only")
    if not training.get("trained"):
        failed.append("not_trained")
    if rows_loaded < min_rows:
        failed.append(f"rows_loaded:{rows_loaded}<{min_rows}")
    if symbol_count < min_symbols:
        failed.append(f"symbol_count:{symbol_count}<{min_symbols}")
    if accuracy is None:
        failed.append("accuracy_missing")
    elif accuracy < min_accuracy:
        failed.append(f"accuracy:{accuracy:.4f}<{min_accuracy:.4f}")
    return CandidateAssessment(
        label_target=str(row.get("label_target") or "unknown"),
        model_id=str(row.get("model_id") or "unknown"),
        rows_loaded=rows_loaded,
        symbol_count=symbol_count,
        accuracy=accuracy,
        trained=bool(training.get("trained")),
        runtime_effect=str(row.get("runtime_effect") or "unknown"),
        diagnostic_path=str(row.get("_diagnostic_path") or ""),
        status="observe_only_candidate_ready" if not failed else "not_ready",
        failed_thresholds=failed,
    )


def _artifact_hygiene(candidate_dir: Path, *, stale_days: int) -> dict[str, Any]:
    now = datetime.now(timezone.utc).timestamp()
    stale_seconds = max(1, stale_days) * 86400
    files = [path for path in candidate_dir.glob("historical_bar_*") if path.is_file()]
    binaries = [path for path in files if path.suffix == ".joblib"]
    diagnostics = [path for path in files if path.name.endswith(".diagnostic.json")]
    stale_binaries = [
        str(path)
        for path in binaries
        if now - path.stat().st_mtime > stale_seconds
    ]
    return {
        "candidate_dir": str(candidate_dir),
        "binary_count": len(binaries),
        "diagnostic_count": len(diagnostics),
        "stale_days": stale_days,
        "stale_binary_count": len(stale_binaries),
        "stale_binaries": stale_binaries[:20],
        "runtime_effect": "report_only_no_deletion",
    }


def prune_historical_bar_model_artifacts(
    *,
    candidate_dir: Path | None = None,
    keep_per_label: int = 2,
    dry_run: bool = True,
) -> dict[str, Any]:
    """Prune older historical-bar binary artifacts while preserving diagnostics."""
    candidate_dir = candidate_dir or DEFAULT_CANDIDATE_DIR
    diagnostics = _diagnostics(candidate_dir)
    by_label: dict[str, list[dict[str, Any]]] = {}
    for row in diagnostics:
        by_label.setdefault(str(row.get("label_target") or "unknown"), []).append(row)
    protected_ids: set[str] = set()
    for rows in by_label.values():
        rows.sort(key=lambda item: str(item.get("generated_at") or ""), reverse=True)
        protected_ids.update(str(row.get("model_id") or "") for row in rows[: max(1, keep_per_label)])

    candidate_files = [
        path
        for path in candidate_dir.glob("historical_bar_*")
        if path.is_file()
        and (
            path.suffix == ".joblib"
            or path.name.endswith(".joblib.metadata.json")
            or path.name.endswith(".baseline.json")
        )
    ]
    deleted: list[str] = []
    would_delete: list[str] = []
    protected: list[str] = []
    for path in candidate_files:
        model_id = path.name
        for suffix in (".joblib.metadata.json", ".baseline.json", ".joblib"):
            if model_id.endswith(suffix):
                model_id = model_id[: -len(suffix)]
                break
        if model_id in protected_ids:
            protected.append(str(path))
            continue
        if dry_run:
            would_delete.append(str(path))
            continue
        try:
            path.unlink()
            deleted.append(str(path))
        except FileNotFoundError:
            continue
    return {
        "report_version": "historical_bar_artifact_prune_v1",
        "runtime_effect": "artifact_cleanup_no_live_authority",
        "candidate_dir": str(candidate_dir),
        "dry_run": dry_run,
        "keep_per_label": keep_per_label,
        "protected_model_ids": sorted(protected_ids),
        "protected_count": len(protected),
        "would_delete_count": len(would_delete),
        "deleted_count": len(deleted),
        "would_delete": would_delete[:50],
        "deleted": deleted[:50],
    }


def run_historical_bar_model_readiness(
    *,
    candidate_dir: Path | None = None,
    min_rows: int = 5000,
    min_symbols: int = 59,
    min_accuracy: float = 0.50,
    stale_days: int = 30,
    prune: bool = False,
    dry_run: bool = True,
    keep_per_label: int = 2,
    limit: int = 12,
) -> bool:
    candidate_dir = candidate_dir or DEFAULT_CANDIDATE_DIR
    rows = _diagnostics(candidate_dir)
    latest = _latest_by_label(rows)
    assessments = [
        _assess(
            row,
            min_rows=min_rows,
            min_symbols=min_symbols,
            min_accuracy=min_accuracy,
        )
        for row in latest.values()
    ]
    assessments.sort(key=lambda item: item.label_target)
    hygiene = _artifact_hygiene(candidate_dir, stale_days=stale_days)
    pruning = (
        prune_historical_bar_model_artifacts(
            candidate_dir=candidate_dir,
            keep_per_label=keep_per_label,
            dry_run=dry_run,
        )
        if prune
        else None
    )

    print()
    print("=" * 72)
    print("  Historical Bar Model Readiness")
    print("=" * 72)
    print(f"report_version          : {HISTORICAL_BAR_MODEL_REPORT_VERSION}")
    print("runtime_effect          : observe_only_report_no_live_authority")
    print(f"candidate_dir           : {candidate_dir}")
    print(f"diagnostics_found       : {len(rows)}")
    print(f"labels_assessed         : {len(assessments)}")
    print(f"min_rows_required       : {min_rows}")
    print(f"min_symbols_required    : {min_symbols}")
    print(f"min_accuracy_required   : {min_accuracy:.4f}")

    print()
    print("Latest candidates by label")
    if assessments:
        for item in assessments[:limit]:
            accuracy_text = "-" if item.accuracy is None else f"{item.accuracy:.4f}"
            failed = ",".join(item.failed_thresholds) if item.failed_thresholds else "-"
            print(
                f"  {item.label_target:<22} {item.status:<30} "
                f"rows={item.rows_loaded:<7} symbols={item.symbol_count:<3} "
                f"accuracy={accuracy_text:<7} failed={failed}"
            )
            print(f"    model_id={item.model_id}")
    else:
        print("  none")

    print()
    print("Artifact hygiene")
    print(f"  binary_count           : {hygiene['binary_count']}")
    print(f"  diagnostic_count       : {hygiene['diagnostic_count']}")
    print(f"  stale_binary_count     : {hygiene['stale_binary_count']}")
    if hygiene["stale_binaries"]:
        for path in hygiene["stale_binaries"][:limit]:
            print(f"  stale                  : {path}")

    if pruning:
        print()
        print("Artifact pruning")
        print(f"  dry_run                : {pruning['dry_run']}")
        print(f"  keep_per_label         : {pruning['keep_per_label']}")
        print(f"  protected_count        : {pruning['protected_count']}")
        print(f"  would_delete_count     : {pruning['would_delete_count']}")
        print(f"  deleted_count          : {pruning['deleted_count']}")
        for path in (pruning["would_delete"] or pruning["deleted"])[:limit]:
            print(f"  prune_candidate        : {path}")

    ok = bool(assessments) and all(item.status == "observe_only_candidate_ready" for item in assessments)
    print()
    if ok:
        print("[OK] latest historical-bar candidates meet observe-only readiness thresholds")
        return True
    print("[WARN] one or more historical-bar candidates are not ready")
    return False
