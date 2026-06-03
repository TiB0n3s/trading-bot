"""Conservative model registry helpers."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ml_platform.config import MODEL_REGISTRY_PATH, MODEL_STATUSES, ensure_ml_dirs

MODEL_ARTIFACT_SUFFIXES = {".joblib", ".pkl", ".pickle", ".bin"}
LIVE_MODEL_STATUSES = {"paper_gate", "paper_soft", "live_candidate", "warn_only"}
CANDIDATE_MODEL_STATUSES = {"candidate", "shadow", "observe_only"}


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
    path.parent.mkdir(parents=True, exist_ok=True)
    registry["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp_path = path.with_name(f".{path.name}.tmp")
    try:
        with tmp_path.open("w") as fh:
            fh.write(json.dumps(registry, indent=2, sort_keys=True) + "\n")
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_path, path)
        try:
            dir_fd = os.open(str(path.parent), os.O_DIRECTORY)
            try:
                os.fsync(dir_fd)
            finally:
                os.close(dir_fd)
        except Exception:
            pass
    except Exception:
        try:
            tmp_path.unlink(missing_ok=True)
        except Exception:
            pass
        raise
    return path


def _parse_iso(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _model_by_id(registry: dict[str, Any], model_id: str) -> dict[str, Any] | None:
    for model in registry.get("models") or []:
        if str(model.get("model_id") or "") == model_id:
            return model
    return None


def model_staleness_guard(
    *,
    model_id: str | None,
    max_age_seconds: int | None,
    registry_path: Path | str = MODEL_REGISTRY_PATH,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a runtime-safe staleness decision for a configured ML model.

    This does not load or execute model code. It only verifies registry metadata
    and artifact freshness so callers can fall back to deterministic policy if a
    promoted model is stale or missing.
    """
    model_id = str(model_id or "").strip()
    max_age_seconds = int(max_age_seconds or 0)
    if not model_id:
        return {
            "status": "not_configured",
            "fallback_required": False,
            "reason": "ML_MODEL_ID not set",
        }
    if max_age_seconds <= 0:
        return {
            "status": "disabled",
            "fallback_required": False,
            "model_id": model_id,
            "reason": "ML_MODEL_MAX_AGE_SECONDS not set",
        }
    registry = load_registry(registry_path)
    model = _model_by_id(registry, model_id)
    if not model:
        return {
            "status": "missing_registry_entry",
            "fallback_required": True,
            "model_id": model_id,
            "max_age_seconds": max_age_seconds,
            "reason": "configured model id not found in registry",
        }
    artifact_path = Path(str(model.get("artifact_path") or ""))
    if not artifact_path.exists():
        return {
            "status": "missing_artifact",
            "fallback_required": True,
            "model_id": model_id,
            "artifact_path": str(artifact_path),
            "max_age_seconds": max_age_seconds,
            "reason": "configured model artifact is missing",
        }
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    mtime = datetime.fromtimestamp(artifact_path.stat().st_mtime, timezone.utc)
    registry_time = _parse_iso(model.get("updated_at") or model.get("created_at"))
    newest = max([item for item in (mtime, registry_time) if item is not None])
    age_seconds = max(0, int((now - newest).total_seconds()))
    fallback_required = age_seconds > max_age_seconds
    return {
        "status": "stale" if fallback_required else "fresh",
        "fallback_required": fallback_required,
        "model_id": model_id,
        "artifact_path": str(artifact_path),
        "artifact_mtime": mtime.isoformat(),
        "registry_timestamp": registry_time.isoformat() if registry_time else None,
        "age_seconds": age_seconds,
        "max_age_seconds": max_age_seconds,
        "fallback_strategy": "deterministic_policy_no_ml_authority",
        "reason": (
            "configured model is stale"
            if fallback_required
            else "configured model freshness is within limit"
        ),
    }


def _artifact_path(model: dict[str, Any]) -> Path | None:
    artifact = str(model.get("artifact_path") or "").strip()
    if not artifact:
        return None
    return Path(artifact)


def prune_model_artifacts(
    *,
    registry_path: Path | str = MODEL_REGISTRY_PATH,
    older_than_days: int = 30,
    fallback_count: int = 3,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Delete stale binary model artifacts while preserving diagnostics.

    The registry remains an audit catalog. This function only unlinks model
    binary files older than the retention window when they are not protected by
    live/candidate/fallback retention rules.
    """
    registry = load_registry(registry_path)
    models = list(registry.get("models") or [])
    now = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    cutoff_seconds = max(0, int(older_than_days)) * 86400

    def created_key(model: dict[str, Any]) -> datetime:
        return _parse_iso(model.get("updated_at") or model.get("created_at")) or datetime.min.replace(tzinfo=timezone.utc)

    protected: set[Path] = set()
    for model in models:
        status = str(model.get("status") or "").lower()
        artifact = _artifact_path(model)
        if artifact and status in LIVE_MODEL_STATUSES | CANDIDATE_MODEL_STATUSES:
            protected.add(artifact)

    fallback_candidates = [
        model
        for model in models
        if _artifact_path(model) is not None
        and str(model.get("status") or "").lower() not in LIVE_MODEL_STATUSES | CANDIDATE_MODEL_STATUSES
    ]
    fallback_candidates.sort(key=created_key, reverse=True)
    for model in fallback_candidates[: max(0, int(fallback_count))]:
        artifact = _artifact_path(model)
        if artifact:
            protected.add(artifact)

    deleted = []
    kept = []
    missing = []
    for model in models:
        artifact = _artifact_path(model)
        if not artifact:
            continue
        if artifact in protected:
            kept.append({"artifact_path": str(artifact), "reason": "protected"})
            continue
        if artifact.suffix not in MODEL_ARTIFACT_SUFFIXES:
            kept.append({"artifact_path": str(artifact), "reason": "non_binary_suffix"})
            continue
        if not artifact.exists():
            missing.append(str(artifact))
            continue
        mtime = datetime.fromtimestamp(artifact.stat().st_mtime, timezone.utc)
        age_seconds = max(0, int((now - mtime).total_seconds()))
        if age_seconds <= cutoff_seconds:
            kept.append({"artifact_path": str(artifact), "reason": "within_retention_window"})
            continue
        artifact.unlink()
        deleted.append(
            {
                "artifact_path": str(artifact),
                "age_seconds": age_seconds,
                "diagnostic_preserved": artifact.with_suffix(
                    artifact.suffix + ".diagnostic.json"
                ).exists(),
            }
        )

    return {
        "report_version": "model_artifact_pruning_v1",
        "runtime_effect": "artifact_hygiene_only_no_live_authority",
        "older_than_days": older_than_days,
        "fallback_count": fallback_count,
        "protected_count": len(protected),
        "deleted_count": len(deleted),
        "deleted": deleted,
        "kept": kept,
        "missing_artifacts": missing,
    }


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
