"""Conservative model registry helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ml_platform.config import MODEL_REGISTRY_PATH, MODEL_STATUSES, ensure_ml_dirs


def load_registry(path: Path | str = MODEL_REGISTRY_PATH) -> dict[str, Any]:
    path = Path(path)
    if not path.exists():
        return {
            "version": 1,
            "updated_at": None,
            "models": [],
        }
    return json.loads(path.read_text())


def save_registry(registry: dict[str, Any], path: Path | str = MODEL_REGISTRY_PATH) -> Path:
    ensure_ml_dirs()
    path = Path(path)
    registry["updated_at"] = datetime.now(timezone.utc).isoformat()
    path.write_text(json.dumps(registry, indent=2, sort_keys=True) + "\n")
    return path


def validate_status(status: str) -> str:
    status = str(status or "research").strip().lower()
    if status not in MODEL_STATUSES:
        allowed = ", ".join(sorted(MODEL_STATUSES))
        raise ValueError(f"invalid model status {status!r}; allowed: {allowed}")
    return status


def register_model(
    *,
    model_id: str,
    artifact_path: str,
    metrics_path: str,
    feature_version: str,
    target: str,
    training_window: str,
    validation_window: str,
    status: str = "research",
    notes: str = "Research only. No runtime use.",
    registry_path: Path | str = MODEL_REGISTRY_PATH,
) -> dict[str, Any]:
    """Insert or update a model registry entry.

    Registry metadata is only an artifact catalog. It does not load models or
    wire them into runtime.
    """
    status = validate_status(status)
    registry = load_registry(registry_path)
    models = registry.setdefault("models", [])

    entry = {
        "model_id": model_id,
        "status": status,
        "artifact_path": artifact_path,
        "metrics_path": metrics_path,
        "feature_version": feature_version,
        "target": target,
        "training_window": training_window,
        "validation_window": validation_window,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "runtime_use": "none" if status == "research" else "requires_explicit_review",
        "notes": notes,
    }

    replaced = False
    for idx, existing in enumerate(models):
        if existing.get("model_id") == model_id:
            entry["created_at"] = existing.get("created_at") or entry["created_at"]
            entry["updated_at"] = datetime.now(timezone.utc).isoformat()
            models[idx] = entry
            replaced = True
            break

    if not replaced:
        models.append(entry)

    save_registry(registry, registry_path)
    return entry
