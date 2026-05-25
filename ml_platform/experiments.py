"""Experiment artifact scaffolding."""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ml_platform.config import EXPERIMENT_ROOT, FEATURE_VERSION, ensure_ml_dirs


def slugify(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9_.-]+", "_", value.strip().lower())
    value = value.strip("._-")
    return value or "experiment"


def create_experiment(
    name: str,
    *,
    dataset_start: str | None = None,
    dataset_end: str | None = None,
    target: str = "ret_fwd_15m",
    notes: str = "Research scaffold only. No runtime use.",
) -> Path:
    """Create an immutable experiment directory with starter metadata."""
    ensure_ml_dirs()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    exp_dir = EXPERIMENT_ROOT / f"{stamp}_{slugify(name)}"
    exp_dir.mkdir(parents=False, exist_ok=False)

    config = {
        "experiment_name": name,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "status": "research",
        "feature_version": FEATURE_VERSION,
        "target": target,
        "dataset_start": dataset_start,
        "dataset_end": dataset_end,
        "split": {
            "type": "walk_forward_placeholder",
            "notes": "Define train/validation windows before training.",
        },
        "runtime_use": "none",
    }

    metrics: dict[str, Any] = {
        "status": "not_run",
        "metrics": {},
        "promotion_allowed": False,
        "notes": "Populate after an offline experiment. Do not promote from placeholder metrics.",
    }

    (exp_dir / "config.json").write_text(json.dumps(config, indent=2, sort_keys=True) + "\n")
    (exp_dir / "metrics.json").write_text(json.dumps(metrics, indent=2, sort_keys=True) + "\n")
    (exp_dir / "feature_columns.txt").write_text("# Add feature column names, one per line.\n")
    (exp_dir / "notes.md").write_text(f"# {name}\n\n{notes}\n")
    return exp_dir
