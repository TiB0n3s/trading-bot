"""Strategy-memory distribution health from concept-drift PSI artifacts."""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any

from services.concept_drift_service import DEFAULT_DRIFT_ARTIFACT_PATH

STRATEGY_MEMORY_DISTRIBUTION_HEALTH_VERSION = "strategy_memory_distribution_health_v1"
STRATEGY_MEMORY_DISTRIBUTION_RUNTIME_EFFECT = "policy_size_down_context_no_order_authority"
DEFAULT_CAUTION_PSI_THRESHOLD = 0.10
DEFAULT_SIZE_DOWN_PSI_THRESHOLD = 0.20
DEFAULT_SEVERE_SIZE_MULTIPLIER = 0.50
DEFAULT_CAUTION_SIZE_MULTIPLIER = 0.75


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        result = float(value)
    except Exception:
        return None
    return result if result == result else None


def _threshold(name: str, default: float) -> float:
    parsed = _float(os.getenv(name))
    return parsed if parsed is not None else default


def _artifact_path(path: str | Path | None = None) -> Path:
    configured = path or os.getenv("STRATEGY_MEMORY_DISTRIBUTION_ARTIFACT_PATH")
    return Path(configured) if configured else DEFAULT_DRIFT_ARTIFACT_PATH


def _load_artifact(path: Path) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None
    return payload if isinstance(payload, dict) else None


def _max_feature_psi(payload: dict[str, Any]) -> tuple[float | None, str | None]:
    rows = payload.get("features") or payload.get("feature_psi") or []
    best_value: float | None = None
    best_feature: str | None = None
    if isinstance(rows, dict):
        rows = [{"feature": key, "psi": value} for key, value in rows.items()]
    for row in rows if isinstance(rows, list) else []:
        if not isinstance(row, dict):
            continue
        value = _float(row.get("psi") or row.get("population_stability_index"))
        if value is None:
            continue
        if best_value is None or value > best_value:
            best_value = value
            best_feature = str(row.get("feature") or row.get("name") or "unknown")
    if best_value is None:
        best_value = _float(payload.get("max_psi"))
        best_feature = (
            str(payload.get("max_psi_feature") or "unknown") if best_value is not None else None
        )
    return best_value, best_feature


def evaluate_strategy_memory_distribution_health(
    *,
    account_state: dict[str, Any] | None = None,
    artifact_path: str | Path | None = None,
    caution_threshold: float | None = None,
    size_down_threshold: float | None = None,
) -> dict[str, Any]:
    """Normalize PSI drift into a deterministic policy input.

    The result has no order authority. Decision policy may consume it to reduce
    buy review size when live feature distributions no longer resemble the
    training baseline.
    """
    account_state = account_state if isinstance(account_state, dict) else {}
    existing = account_state.get("strategy_memory_distribution_health") or account_state.get(
        "distribution_health"
    )
    if isinstance(existing, dict):
        return existing

    path = _artifact_path(artifact_path)
    payload = _load_artifact(path)
    caution = (
        caution_threshold
        if caution_threshold is not None
        else _threshold("STRATEGY_MEMORY_PSI_CAUTION_THRESHOLD", DEFAULT_CAUTION_PSI_THRESHOLD)
    )
    size_down = (
        size_down_threshold
        if size_down_threshold is not None
        else _threshold(
            "STRATEGY_MEMORY_PSI_SIZE_DOWN_THRESHOLD",
            DEFAULT_SIZE_DOWN_PSI_THRESHOLD,
        )
    )
    base = {
        "version": STRATEGY_MEMORY_DISTRIBUTION_HEALTH_VERSION,
        "runtime_effect": STRATEGY_MEMORY_DISTRIBUTION_RUNTIME_EFFECT,
        "artifact_path": str(path),
        "caution_threshold": caution,
        "size_down_threshold": size_down,
        "decision": "pass",
        "status": "missing",
        "size_multiplier": 1.0,
        "max_psi": None,
        "max_psi_feature": None,
        "reason": "concept drift artifact unavailable",
    }
    if not payload:
        return base

    max_psi, feature = _max_feature_psi(payload)
    severe = bool(payload.get("severe_drift"))
    if severe or (max_psi is not None and max_psi >= size_down):
        decision = "size_down"
        status = "severe_drift" if severe else "distribution_drift"
        multiplier = DEFAULT_SEVERE_SIZE_MULTIPLIER
        reason = (
            "strategy-memory PSI drift exceeds size-down threshold: "
            f"max_psi={max_psi} feature={feature}"
        )
    elif max_psi is not None and max_psi >= caution:
        decision = "caution"
        status = "moderate_drift"
        multiplier = DEFAULT_CAUTION_SIZE_MULTIPLIER
        reason = (
            "strategy-memory PSI drift exceeds caution threshold: "
            f"max_psi={max_psi} feature={feature}"
        )
    else:
        decision = "pass"
        status = "stable"
        multiplier = 1.0
        reason = "strategy-memory feature distribution remains within PSI thresholds"

    return {
        **base,
        "decision": decision,
        "status": status,
        "size_multiplier": multiplier,
        "max_psi": round(max_psi, 6) if max_psi is not None else None,
        "max_psi_feature": feature,
        "severe_drift": severe,
        "artifact_created_at": payload.get("created_at"),
        "reason": reason,
    }
