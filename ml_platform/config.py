"""Shared paths and status constants for ML research tooling."""

from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
ML_ROOT = PROJECT_ROOT / "ml"
DATASET_ROOT = ML_ROOT / "datasets"
EXPERIMENT_ROOT = ML_ROOT / "experiments"
MODEL_ROOT = ML_ROOT / "models"
MODEL_REGISTRY_PATH = MODEL_ROOT / "registry.json"

FEATURE_VERSION = "feature_snapshots_v3"

MODEL_STATUSES = {
    "research",
    "observe_only",
    "warn_only",
    "paper_gate",
    "live_candidate",
    "shadow",
    "paper_soft",
    "retired",
}


def ensure_ml_dirs() -> None:
    """Create local ML artifact directories.

    This only touches files under ml/. It does not alter runtime, cron, broker,
    risk controls, or trades.db.
    """
    for path in (DATASET_ROOT, EXPERIMENT_ROOT, MODEL_ROOT):
        path.mkdir(parents=True, exist_ok=True)
