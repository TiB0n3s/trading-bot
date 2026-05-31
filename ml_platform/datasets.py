"""Read-only dataset profiling helpers."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ml_platform.config import DEFAULT_DB_PATH, FEATURE_VERSION
from repositories.training_data_repo import TrainingDataRepository


def dataset_profile(
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Return a read-only profile of ML-relevant tables."""
    db_path = Path(db_path)
    date_where = ""
    params: tuple[str, ...] = ()

    if start_date and end_date:
        date_where = "substr(timestamp, 1, 10) BETWEEN ? AND ?"
        params = (start_date, end_date)
    elif start_date or end_date:
        raise ValueError("Provide both start_date and end_date, or neither")

    repo = TrainingDataRepository(db_path)
    snapshots = repo.table_count("feature_snapshots", date_where, params)
    labels = repo.table_count("labeled_setups", date_where, params) if date_where else repo.table_count("labeled_setups")
    matched_trades = repo.table_count("matched_trades")
    context_rows = repo.table_count("daily_symbol_context")
    event_rows = repo.table_count("daily_symbol_events")
    prediction_rows = repo.table_count("daily_symbol_predictions")
    symbols = repo.distinct_feature_snapshot_symbols(date_where, params)
    snapshot_range = repo.min_max("feature_snapshots", "timestamp")

    label_coverage = (
        round((labels / snapshots) * 100.0, 2)
        if snapshots and labels is not None
        else 0.0
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_path": str(db_path),
        "feature_version": FEATURE_VERSION,
        "start_date": start_date,
        "end_date": end_date,
        "tables": {
            "feature_snapshots": snapshots,
            "labeled_setups": labels,
            "matched_trades": matched_trades,
            "daily_symbol_context": context_rows,
            "daily_symbol_events": event_rows,
            "daily_symbol_predictions": prediction_rows,
        },
        "feature_snapshots_range": snapshot_range,
        "distinct_snapshot_symbols": symbols,
        "label_coverage_pct": label_coverage,
        "ready_for_training": bool(snapshots and labels and snapshots >= 500 and label_coverage >= 50.0),
        "notes": [
            "Profile is read-only.",
            "Training is not recommended below 500 labeled snapshots.",
            "Predictions remain observe-only.",
        ],
    }


def write_profile(profile: dict[str, Any], output: Path | str) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n")
    return path
