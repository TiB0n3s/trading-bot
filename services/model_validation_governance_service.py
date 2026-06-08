"""Consolidated model validation governance diagnostics."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ml_platform.config import MODEL_REGISTRY_PATH, MODEL_ROOT

DEFAULT_HISTORICAL_CANDIDATE_DIR = MODEL_ROOT / "historical_bar_patterns_v1" / "candidates"
LIVE_AUTHORITY_STATUSES = {"live", "live_gate", "live_block", "production"}


def _read_json(path: Path) -> dict[str, Any] | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _latest_historical_candidates(candidate_dir: Path) -> list[dict[str, Any]]:
    latest: dict[str, dict[str, Any]] = {}
    for path in sorted(candidate_dir.glob("historical_bar_*_*.diagnostic.json")):
        payload = _read_json(path)
        if not payload:
            continue
        payload["_path"] = str(path)
        label = str(payload.get("label_target") or "unknown")
        current = latest.get(label)
        if current is None or str(payload.get("generated_at") or "") > str(
            current.get("generated_at") or ""
        ):
            latest[label] = payload
    return list(latest.values())


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
    min_rows: int = 5000,
    min_symbols: int = 20,
    min_accuracy: float = 0.50,
) -> dict[str, Any]:
    candidate_dir = candidate_dir or DEFAULT_HISTORICAL_CANDIDATE_DIR
    registry_path = registry_path or MODEL_REGISTRY_PATH
    candidates = _latest_historical_candidates(candidate_dir)
    assessed = []
    blockers: list[str] = []
    for row in candidates:
        training = row.get("training") or {}
        rows_loaded = int(row.get("rows_loaded") or 0)
        symbol_count = int(row.get("symbol_count") or 0)
        accuracy = training.get("accuracy")
        accuracy_float = float(accuracy) if accuracy is not None else None
        failed = []
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
        blockers.extend(f"{row.get('label_target') or 'unknown'}:{item}" for item in failed)
        assessed.append(
            {
                "label_target": row.get("label_target") or "unknown",
                "model_id": row.get("model_id") or "unknown",
                "rows_loaded": rows_loaded,
                "symbol_count": symbol_count,
                "accuracy": accuracy_float,
                "runtime_effect": row.get("runtime_effect") or "unknown",
                "status": "observe_only_ready" if not failed else "not_ready",
                "failed_thresholds": failed,
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

    ready_count = sum(1 for row in assessed if row["status"] == "observe_only_ready")
    return {
        "report_version": "model_validation_governance_v1",
        "runtime_effect": "diagnostic_only_no_registry_or_runtime_authority_change",
        "candidate_dir": str(candidate_dir),
        "registry_path": str(registry_path),
        "labels_assessed": len(assessed),
        "ready_label_count": ready_count,
        "registry_entry_count": len(registry_entries),
        "live_registry_entry_count": len(live_entries),
        "candidates": sorted(assessed, key=lambda row: str(row["label_target"])),
        "blockers": blockers,
        "ready_for_observe_only_validation": ready_count > 0 and not live_entries,
        "ready_for_live_promotion": False,
        "notes": [
            "This report cannot promote models or load runtime artifacts.",
            "Live promotion remains blocked without explicit operator approval and session evidence.",
            "Candidate quality must still be compared against baseline behavior, costs, slippage, exits, and regimes.",
        ],
    }
