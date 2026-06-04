"""Adapters from existing bot intelligence into offline ML feature rows.

This module is intentionally offline/read-only. It converts already-collected
SQLite rows into ML-ready "brain" features using deterministic bot logic where
it is safe to do so.
"""

from __future__ import annotations

import csv
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ml_platform.config import DEFAULT_DB_PATH
from repositories.training_data_repo import TrainingDataRepository
from setup_engine import classify_feature_snapshot as classify_setup


BRAIN_FEATURE_VERSION = "bot_brain_features_v1"

BRAIN_LOGIC_SOURCES = {
    "setup_engine": "setup_engine.classify_feature_snapshot",
    "context": "daily_symbol_context",
    "events": "daily_symbol_events aggregate count",
    "predictions": "daily_symbol_predictions observe-only rows",
}

BRAIN_FEATURE_COLUMNS = [
    "brain_feature_version",
    "snapshot_id",
    "snapshot_date",
    "timestamp",
    "symbol",
    "snapshot_ret_1m",
    "snapshot_ret_5m",
    "snapshot_ret_15m",
    "snapshot_relative_strength_5m",
    "snapshot_distance_from_vwap",
    "snapshot_volume_ratio_5m",
    "snapshot_trend_direction",
    "snapshot_trend_strength",
    "bot_setup_label",
    "bot_setup_recommendation",
    "bot_setup_score",
    "bot_setup_confidence",
    "bot_setup_key",
    "bot_setup_rationale",
    "trend_bucket",
    "vwap_bucket",
    "relative_strength_bucket",
    "context_bias",
    "context_confidence",
    "context_risk_level",
    "context_entry_quality",
    "context_catalyst_score",
    "context_relative_strength_score",
    "event_count",
    "prediction_score",
    "prediction_confidence",
    "prediction_sample_size",
    "prediction_trend_label",
    "prediction_timing_score",
    "bar_pattern_label",
    "bar_pattern_score",
    "candle_body_pct",
    "close_location",
    "range_atr_ratio",
    "volume_weighted_pressure_3",
    "cvd_price_corr_20",
    "vpin_toxicity_20",
    "fractional_diff_zscore_20",
    "triple_barrier_label",
    "trend_scan_label",
    "trend_scan_tstat",
    "outcome_label",
    "ret_fwd_15m",
    "ret_fwd_30m",
]


def _date_filter(date_arg: str | None, start_date: str | None, end_date: str | None) -> tuple[str, tuple[str, ...]]:
    if date_arg and (start_date or end_date):
        raise ValueError("Use either date or start/end range, not both")
    if date_arg:
        return "substr(fs.timestamp, 1, 10) = ?", (date_arg,)
    if start_date and end_date:
        return "substr(fs.timestamp, 1, 10) BETWEEN ? AND ?", (start_date, end_date)
    raise ValueError("Provide date or both start_date and end_date")


def fetch_brain_source_rows(
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
    date_arg: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[Any]:
    """Fetch source rows for offline brain feature generation."""
    where_sql, params = _date_filter(date_arg, start_date, end_date)
    return TrainingDataRepository(db_path).brain_source_rows(where_sql, params)


def build_brain_feature_row(row: Any | dict[str, Any]) -> dict[str, Any]:
    """Build one ML feature row from a feature_snapshot-like row."""
    data = dict(row)
    setup = classify_setup(data)

    return {
        "brain_feature_version": BRAIN_FEATURE_VERSION,
        "snapshot_id": data.get("id") or data.get("snapshot_id"),
        "snapshot_date": data.get("snapshot_date") or str(data.get("timestamp") or "")[:10],
        "timestamp": data.get("timestamp"),
        "symbol": data.get("symbol"),
        "snapshot_ret_1m": data.get("ret_1m"),
        "snapshot_ret_5m": data.get("ret_5m"),
        "snapshot_ret_15m": data.get("ret_15m"),
        "snapshot_relative_strength_5m": data.get("relative_strength_5m"),
        "snapshot_distance_from_vwap": data.get("distance_from_vwap"),
        "snapshot_volume_ratio_5m": data.get("volume_ratio_5m"),
        "snapshot_trend_direction": data.get("trend_direction"),
        "snapshot_trend_strength": data.get("trend_strength"),
        "bot_setup_label": setup.setup_label,
        "bot_setup_recommendation": setup.recommendation,
        "bot_setup_score": setup.setup_score,
        "bot_setup_confidence": setup.confidence,
        "bot_setup_key": setup.setup_key,
        "bot_setup_rationale": setup.rationale,
        "trend_bucket": setup.trend_bucket,
        "vwap_bucket": setup.vwap_bucket,
        "relative_strength_bucket": setup.rs_bucket,
        "context_bias": data.get("context_bias"),
        "context_confidence": data.get("context_confidence"),
        "context_risk_level": data.get("context_risk_level"),
        "context_entry_quality": data.get("context_entry_quality"),
        "context_catalyst_score": data.get("context_catalyst_score"),
        "context_relative_strength_score": data.get("context_relative_strength_score"),
        "event_count": data.get("event_count"),
        "prediction_score": data.get("prediction_score"),
        "prediction_confidence": data.get("prediction_confidence"),
        "prediction_sample_size": data.get("prediction_sample_size"),
        "prediction_trend_label": data.get("prediction_trend_label"),
        "prediction_timing_score": data.get("prediction_timing_score"),
        "bar_pattern_label": data.get("bar_pattern_label"),
        "bar_pattern_score": data.get("bar_pattern_score"),
        "candle_body_pct": data.get("candle_body_pct"),
        "close_location": data.get("close_location"),
        "range_atr_ratio": data.get("range_atr_ratio"),
        "volume_weighted_pressure_3": data.get("volume_weighted_pressure_3"),
        "cvd_price_corr_20": data.get("cvd_price_corr_20"),
        "vpin_toxicity_20": data.get("vpin_toxicity_20"),
        "fractional_diff_zscore_20": data.get("fractional_diff_zscore_20"),
        "triple_barrier_label": data.get("triple_barrier_label"),
        "trend_scan_label": data.get("trend_scan_label"),
        "trend_scan_tstat": data.get("trend_scan_tstat"),
        "outcome_label": data.get("outcome_label"),
        "ret_fwd_15m": data.get("ret_fwd_15m"),
        "ret_fwd_30m": data.get("ret_fwd_30m"),
    }


def build_brain_feature_rows(
    *,
    db_path: Path | str = DEFAULT_DB_PATH,
    date_arg: str | None = None,
    start_date: str | None = None,
    end_date: str | None = None,
) -> list[dict[str, Any]]:
    rows = fetch_brain_source_rows(
        db_path=db_path,
        date_arg=date_arg,
        start_date=start_date,
        end_date=end_date,
    )
    return [build_brain_feature_row(row) for row in rows]


def write_brain_features_csv(rows: list[dict[str, Any]], output: Path | str) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BRAIN_FEATURE_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row.get(col) for col in BRAIN_FEATURE_COLUMNS})
    return path


def brain_feature_manifest(rows: list[dict[str, Any]]) -> dict[str, Any]:
    symbols = {r.get("symbol") for r in rows if r.get("symbol")}
    labeled = sum(1 for r in rows if r.get("outcome_label") is not None)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "brain_feature_version": BRAIN_FEATURE_VERSION,
        "logic_sources": BRAIN_LOGIC_SOURCES,
        "rows": len(rows),
        "symbols": len(symbols),
        "labeled_rows": labeled,
        "columns": BRAIN_FEATURE_COLUMNS,
        "runtime_use": "none",
        "notes": [
            "Offline feature adapter only.",
            "Uses deterministic bot setup logic as model features.",
            "Does not write to trades.db or affect decisions.",
        ],
    }
