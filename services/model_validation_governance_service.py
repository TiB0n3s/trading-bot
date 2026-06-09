"""Consolidated model validation governance diagnostics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ml_platform.config import MODEL_REGISTRY_PATH, MODEL_ROOT
from ml_platform.lifecycle import (
    REQUIRED_PROMOTION_METRICS,
    validation_method_is_promotion_eligible,
    validation_method_is_simple_split,
)

DEFAULT_HISTORICAL_CANDIDATE_DIR = MODEL_ROOT / "historical_bar_patterns_v1" / "candidates"
LIVE_AUTHORITY_STATUSES = {"live", "live_gate", "live_block", "production"}
DEFAULT_PROMOTION_EVIDENCE_DIR = Path("ops/model_promotion_evidence")
REQUIRED_PROMOTION_EVIDENCE = {
    "dataset_manifest.json": "dataset manifest",
    "feature_parity.json": "feature parity validation",
    "purged_walk_forward.json": "purged walk-forward validation",
    "calibration_report.json": "calibration report",
    "replay_decision_delta.json": "replay decision delta",
    "baseline_comparison.json": "baseline comparison",
    "cost_slippage_exit_analysis.json": "cost/slippage/exit analysis",
    "regime_stability.json": "regime stability",
    "live_observation_window.json": "live observation window",
    "shadow_serving.json": "shadow serving contract",
    "rollback_demotion.json": "rollback/demotion plan",
    "operator_approval.json": "explicit operator approval",
}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _candidate_quality(payload: dict[str, Any]) -> tuple[bool, float, int, str]:
    training = payload.get("training") or {}
    return (
        bool(training.get("trained")),
        float(training.get("accuracy") or 0.0),
        int(payload.get("rows_loaded") or 0),
        str(payload.get("generated_at") or ""),
    )


def _best_historical_candidates(candidate_dir: Path) -> list[dict[str, Any]]:
    best: dict[str, dict[str, Any]] = {}
    for path in sorted(candidate_dir.glob("historical_bar_*_*.diagnostic.json")):
        payload = _read_json(path)
        if not payload:
            continue
        payload["_path"] = str(path)
        label = str(payload.get("label_target") or "unknown")
        current = best.get(label)
        if current is None or _candidate_quality(payload) > _candidate_quality(current):
            best[label] = payload
    return list(best.values())


def _registry_entries(registry_path: Path) -> list[dict[str, Any]]:
    payload = _read_json(registry_path)
    if not payload:
        return []
    if isinstance(payload.get("models"), list):
        return [row for row in payload["models"] if isinstance(row, dict)]
    entries = payload.get("entries")
    if isinstance(entries, list):
        return [row for row in entries if isinstance(row, dict)]
    if isinstance(entries, dict):
        return [row for row in entries.values() if isinstance(row, dict)]
    return []


def build_model_validation_governance_payload(
    *,
    candidate_dir: Path | None = None,
    registry_path: Path | None = None,
    promotion_evidence_dir: Path | None = None,
    min_rows: int = 5000,
    min_symbols: int = 20,
    min_accuracy: float = 0.50,
) -> dict[str, Any]:
    candidate_dir = candidate_dir or DEFAULT_HISTORICAL_CANDIDATE_DIR
    registry_path = registry_path or MODEL_REGISTRY_PATH
    promotion_evidence_dir = promotion_evidence_dir or DEFAULT_PROMOTION_EVIDENCE_DIR
    candidates = _best_historical_candidates(candidate_dir)
    assessed = []
    blockers: list[str] = []
    candidate_registration_blockers: list[str] = []
    for row in candidates:
        training = row.get("training") or {}
        rows_loaded = int(row.get("rows_loaded") or 0)
        symbol_count = int(row.get("symbol_count") or 0)
        accuracy = training.get("accuracy")
        accuracy_float = float(accuracy) if accuracy is not None else None
        validation_method = str(
            training.get("validation_method") or row.get("validation_method") or "unknown"
        )
        promotion_metrics = training.get("promotion_metrics") or row.get("promotion_metrics") or {}
        failed = []
        registration_failed = []
        if row.get("runtime_effect") != "observe_only_no_live_authority":
            failed.append("runtime_effect_not_observe_only")
        if not training.get("trained"):
            failed.append("not_trained")
        if rows_loaded < min_rows:
            failed.append(f"rows_loaded:{rows_loaded}<{min_rows}")
        if symbol_count < min_symbols:
            failed.append(f"symbol_count:{symbol_count}<{min_symbols}")
        if accuracy_float is None:
            failed.append("accuracy_missing")
        elif accuracy_float < min_accuracy:
            failed.append(f"accuracy:{accuracy_float:.4f}<{min_accuracy:.4f}")
        if validation_method_is_simple_split(validation_method):
            registration_failed.append(
                "validation:simple_split_not_candidate_registration_eligible"
            )
        elif not validation_method_is_promotion_eligible(validation_method):
            registration_failed.append(f"validation:not_purged_walk_forward:{validation_method}")
        missing_metrics = [
            key for key in REQUIRED_PROMOTION_METRICS if promotion_metrics.get(key) is None
        ]
        registration_failed.extend(f"metrics:missing:{key}" for key in missing_metrics)
        blockers.extend(f"{row.get('label_target') or 'unknown'}:{item}" for item in failed)
        candidate_registration_blockers.extend(
            f"{row.get('label_target') or 'unknown'}:{item}" for item in registration_failed
        )
        assessed.append(
            {
                "label_target": row.get("label_target") or "unknown",
                "model_id": row.get("model_id") or "unknown",
                "rows_loaded": rows_loaded,
                "symbol_count": symbol_count,
                "accuracy": accuracy_float,
                "validation_method": validation_method,
                "promotion_metric_count": len(
                    [
                        key
                        for key in REQUIRED_PROMOTION_METRICS
                        if promotion_metrics.get(key) is not None
                    ]
                ),
                "missing_promotion_metrics": missing_metrics,
                "runtime_effect": row.get("runtime_effect") or "unknown",
                "status": "observe_only_ready" if not failed else "not_ready",
                "failed_thresholds": failed,
                "candidate_registration_status": (
                    "ready" if not failed and not registration_failed else "not_ready"
                ),
                "candidate_registration_failed_thresholds": registration_failed,
            }
        )

    if not assessed:
        blockers.append("historical_bar_candidates:missing")

    registry_entries = _registry_entries(registry_path)
    live_entries = [
        row
        for row in registry_entries
        if str(row.get("status") or "").strip().lower() in LIVE_AUTHORITY_STATUSES
    ]
    if live_entries:
        blockers.append("registry:live_authority_status_present")

    promotion_evidence = []
    promotion_evidence_blockers = []
    for filename, label in REQUIRED_PROMOTION_EVIDENCE.items():
        path = promotion_evidence_dir / filename
        payload = _read_json(path) if path.exists() else None
        valid = bool(payload and payload.get("ready") is True)
        if not valid:
            promotion_evidence_blockers.append(f"promotion_evidence:{filename}")
        promotion_evidence.append(
            {
                "name": label,
                "path": str(path),
                "present": path.exists(),
                "ready": valid,
            }
        )

    ready_count = sum(1 for row in assessed if row["status"] == "observe_only_ready")
    candidate_registration_ready_count = sum(
        1 for row in assessed if row["candidate_registration_status"] == "ready"
    )
    return {
        "report_version": "model_validation_governance_v1",
        "runtime_effect": "diagnostic_only_no_registry_or_runtime_authority_change",
        "candidate_dir": str(candidate_dir),
        "registry_path": str(registry_path),
        "promotion_evidence_dir": str(promotion_evidence_dir),
        "labels_assessed": len(assessed),
        "ready_label_count": ready_count,
        "candidate_registration_ready_count": candidate_registration_ready_count,
        "registry_entry_count": len(registry_entries),
        "live_registry_entry_count": len(live_entries),
        "candidates": sorted(assessed, key=lambda row: str(row["label_target"])),
        "promotion_evidence": promotion_evidence,
        "promotion_evidence_blockers": promotion_evidence_blockers,
        "blockers": blockers,
        "candidate_registration_blockers": candidate_registration_blockers,
        "ready_for_observe_only_validation": ready_count > 0 and not live_entries,
        "ready_for_candidate_registration": bool(
            candidate_registration_ready_count > 0
            and not live_entries
            and not candidate_registration_blockers
        ),
        "ready_for_live_promotion": bool(
            candidate_registration_ready_count > 0
            and not live_entries
            and not blockers
            and not candidate_registration_blockers
            and not promotion_evidence_blockers
        ),
        "notes": [
            "This report cannot promote models or load runtime artifacts.",
            "Live promotion remains blocked without explicit operator approval and session evidence.",
            "Candidate registration requires purged walk-forward validation and required promotion metrics.",
            "Candidate quality must be compared against baseline behavior, costs, slippage, exits, regimes, calibration, and replay decision deltas.",
        ],
    }
