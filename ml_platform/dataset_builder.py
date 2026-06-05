"""Canonical training dataset builder for the ML platform.

This is the authoritative module for constructing point-in-time safe training
rows from trades.db. Dataset exports, staging readiness checks, and model
training pipelines should source rows from here rather than implementing their
own joins.

This module is read-only with respect to trades.db and the broker. It does not
train models, place orders, or modify runtime behavior.

Typical use:

    from ml_platform.dataset_builder import DatasetBuildConfig, build_training_dataset

    config = DatasetBuildConfig(start_date="2026-05-01", end_date="2026-05-26")
    result = build_training_dataset(config)
    # result.rows — list of dicts, training-ready by default
    # result.manifest — governance audit manifest
"""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ml_platform.config import DEFAULT_DB_PATH, FEATURE_VERSION
from ml_platform.governance import build_dataset_manifest
from ml_platform.pit_context import get_archive_root, pit_coverage_for_range
from repositories.training_data_repo import TrainingDataRepository
from symbols_config import SYMBOL_UNIVERSE_VERSION


QUERY_VERSION = "ml_dataset_builder_v1"
LABEL_VERSION = "label_taxonomy_v1"
BAR_PATTERN_FEATURE_TARGET_VERSION = "bar_pattern_feature_target_v1"
ADVANCED_ALPHA_FEATURE_VERSION = "advanced_alpha_feature_target_v1"

FIXED_HORIZON_TARGETS = [
    "ret_fwd_15m",
    "ret_fwd_30m",
    "max_up_15m",
    "max_down_15m",
    "triple_barrier_label",
    "trend_scan_label",
]

FUTURE_FIXED_HORIZON_TARGETS = [
    "ret_fwd_60m",
    "max_favorable_excursion",
    "max_adverse_excursion",
]

# Definitive column order for a built training row.
ROW_COLUMNS = [
    # Snapshot identity
    "snapshot_id",
    "snapshot_date",
    "timestamp",
    "symbol",
    "last_price",
    # Price/volume features
    "ret_1m",
    "ret_5m",
    "ret_15m",
    "range_pos_15m",
    "distance_from_5m_high",
    "distance_from_5m_low",
    "distance_from_vwap",
    "volume_ratio_5m",
    # Benchmark
    "benchmark_symbol",
    "benchmark_ret_5m",
    "relative_strength_5m",
    "spread_pct",
    # Market context
    "market_session",
    "macro_regime",
    "market_bias",
    "trend_direction",
    "trend_strength",
    # PIT feature audit fields (LEAKAGE_POLICY required fields)
    "feature_available_at",
    "feature_generated_at",
    "feature_age_seconds",
    "source",
    "is_stale",
    "staleness_reason",
    # Setup engine
    "bar_timeframe",
    "bar_count",
    "setup_label",
    "setup_recommendation",
    "setup_score",
    "setup_confidence",
    "setup_key",
    # Observe-only candle physics / pattern learning features
    "bar_pattern_feature_version",
    "ema_12",
    "ema_26",
    "macd",
    "macd_signal",
    "rsi_14",
    "candle_body_pct",
    "upper_wick_pct",
    "lower_wick_pct",
    "upper_lower_wick_ratio",
    "close_location",
    "range_atr_ratio",
    "atr_20_pct",
    "volume_ratio_20",
    "pressure_return_3",
    "pressure_return_8",
    "volume_weighted_pressure_3",
    "volume_delta",
    "institutional_volume_delta",
    "cumulative_volume_delta",
    "cvd_price_corr_20",
    "cvd_divergence_label",
    "vpin_toxicity_20",
    "fractional_diff_close_045",
    "fractional_diff_zscore_20",
    "trend_scan_label",
    "trend_scan_tstat",
    "trend_scan_bars",
    "trend_scan_return_pct",
    "trend_scan_reason",
    "bar_pattern_label",
    "bar_pattern_score",
    "bar_opportunity_action",
    "bar_opportunity_quality",
    "bar_long_opportunity_score",
    "bar_sell_opportunity_score",
    # Fixed-horizon labels (from labeled_setups)
    "future_price_5m",
    "future_price_15m",
    "future_price_30m",
    "ret_fwd_5m",
    "ret_fwd_15m",
    "ret_fwd_30m",
    "max_up_15m",
    "max_down_15m",
    "outcome_label",
    # Triple-barrier label metadata (from bar_pattern_features)
    "triple_barrier_label",
    "triple_barrier_reason",
    "triple_barrier_bars_to_event",
    "triple_barrier_profit_pct",
    "triple_barrier_stop_pct",
    # Daily context (from daily_symbol_context)
    "context_bias",
    "context_confidence",
    "context_risk_level",
    "context_entry_quality",
    "context_catalyst_score",
    "context_relative_strength_score",
    "context_sector_alignment",
    "context_index_alignment",
    # Observe-only predictions (from daily_symbol_predictions)
    "prediction_score",
    "probability_of_profit",
    "probability_of_order",
    "expected_pnl",
    "prediction_confidence",
    "prediction_sample_size",
    # Label metadata
    "label_horizon_status",
    "label_target_family",
    "realized_exit_label_status",
    "exit_policy_version",
    "position_manager_version",
    # PIT archive coverage — injected per row from point_in_time archives
    "pit_archive_id",
    "pit_coverage_status",
]

# Fields that must be present in feature_snapshots for a PIT-clean export.
_REQUIRED_PIT_AUDIT_FIELDS = (
    "feature_available_at",
    "feature_generated_at",
    "feature_age_seconds",
    "source",
    "is_stale",
    "staleness_reason",
)


@dataclass
class DatasetBuildConfig:
    """Parameters controlling a training dataset build."""

    start_date: str                  # YYYY-MM-DD inclusive
    end_date: str                    # YYYY-MM-DD inclusive
    db_path: Path | None = None
    include_incomplete_labels: bool = False
    query_version: str = QUERY_VERSION
    label_version: str = LABEL_VERSION


@dataclass
class DatasetBuildResult:
    """Output of build_training_dataset()."""

    rows: list[dict[str, Any]]
    source_row_count: int
    export_row_count: int
    complete_horizon_rows: int
    labeled_rows: int
    symbols: set[str]
    start_date: str
    end_date: str
    excluded_reason_counts: dict[str, int]
    pit_contract: dict[str, Any]    # feature snapshot audit contract
    pit_coverage: dict[str, Any]    # archive coverage summary for date range
    manifest: dict[str, Any]        # governance manifest (DatasetManifest.to_dict() + export fields)
    label_horizon_statuses: list[str]
    safe_training_targets: list[str] = field(
        default_factory=lambda: list(FIXED_HORIZON_TARGETS)
    )


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------

def _fetch_raw_rows(
    db_path: Path,
    start_date: str,
    end_date: str,
) -> list[Any]:
    """Run the canonical join and return all rows for the date range."""
    return TrainingDataRepository(db_path).raw_training_rows(start_date, end_date)


def _exclusion_counts(rows: list[Any]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        status = r["label_horizon_status"] or "unlabeled"
        if status != "complete":
            counts[status] = counts.get(status, 0) + 1
    return counts


def _inject_pit_archive(
    rows: list[Any],
    pit_coverage: dict[str, Any],
) -> list[dict[str, Any]]:
    """Convert rows to dicts and inject pit_archive_id / pit_coverage_status.

    Uses the already-computed pit_coverage summary rather than re-querying the
    archive for every row, so cost is O(dates) not O(rows).
    """
    per_date: dict[str, str | None] = pit_coverage.get("per_date", {})
    fallback_set = set(pit_coverage.get("fallback_dates", []))

    date_to_status: dict[str, str] = {}
    for d, archive_id in per_date.items():
        if archive_id is None:
            date_to_status[d] = "missing"
        elif d in fallback_set:
            date_to_status[d] = "prior_date_fallback"
        else:
            date_to_status[d] = "exact"

    result = []
    for r in rows:
        row = dict(r)
        date = row.get("snapshot_date") or ""
        row["pit_archive_id"] = per_date.get(date)
        row["pit_coverage_status"] = date_to_status.get(date, "unknown")
        result.append(row)
    return result


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def validate_pit_contract(db_path: Path | None = None) -> dict[str, Any]:
    """Check whether feature_snapshots satisfies the PIT audit field contract.

    Returns a dict with keys:
      ok                          — True only if all required fields are present
      missing_feature_audit_fields — list of absent field names
      stale_feature_snapshot_count — count of rows where is_stale != 0
      table_exists                — False when the table is not yet migrated

    Does not raise. Callers decide whether to treat missing fields as a hard
    block or a warning.
    """
    path = db_path or DEFAULT_DB_PATH
    return TrainingDataRepository(path).pit_contract(_REQUIRED_PIT_AUDIT_FIELDS)


def build_training_dataset(config: DatasetBuildConfig) -> DatasetBuildResult:
    """Build a point-in-time safe training dataset from trades.db.

    Steps:
    1. Validate the PIT feature audit contract (non-blocking; recorded in result).
    2. Run the canonical SQL join across feature_snapshots, labeled_setups,
       daily_symbol_context, and daily_symbol_predictions.
    3. Count excluded rows by label_horizon_status.
    4. Filter to complete-horizon rows only (default) or keep all (audit mode).
    5. Compute PIT archive coverage for the date range.
    6. Inject pit_archive_id and pit_coverage_status into each row dict.
    7. Build the governance manifest.
    8. Return a DatasetBuildResult with rows and all audit metadata.

    Args:
        config: DatasetBuildConfig controlling date range, db path, and filters.

    Returns:
        DatasetBuildResult. result.rows is the training-ready list of dicts.

    Raises:
        RuntimeError: if feature_snapshots or labeled_setups are missing.
    """
    db_path = Path(config.db_path) if config.db_path else DEFAULT_DB_PATH
    archive_root = get_archive_root(db_path.parent)

    pit_contract = validate_pit_contract(db_path)
    raw_rows = _fetch_raw_rows(db_path, config.start_date, config.end_date)
    exclusion_counts = _exclusion_counts(raw_rows)

    if config.include_incomplete_labels:
        export_sqlite_rows = raw_rows
    else:
        export_sqlite_rows = [
            r for r in raw_rows
            if (r["label_horizon_status"] or "unlabeled") == "complete"
        ]

    pit_coverage = pit_coverage_for_range(
        config.start_date,
        config.end_date,
        archive_root=archive_root,
    )

    rows = _inject_pit_archive(export_sqlite_rows, pit_coverage)

    manifest = build_dataset_manifest(
        db_path=db_path,
        start_date=config.start_date,
        end_date=config.end_date,
        query_version=config.query_version,
        label_version=config.label_version,
        excluded_rows_reason_counts=exclusion_counts,
        pit_coverage=pit_coverage,
    )
    complete_horizon_rows = sum(
        1 for r in raw_rows if (r["label_horizon_status"] or "unlabeled") == "complete"
    )
    manifest["source_row_count"] = len(raw_rows)
    manifest["export_row_count"] = len(rows)
    manifest["complete_horizon_rows"] = complete_horizon_rows
    manifest["training_default_complete_horizon_only"] = not config.include_incomplete_labels
    manifest["included_label_horizon_statuses"] = sorted(
        {r.get("label_horizon_status") or "unlabeled" for r in rows}
    )
    manifest["label_scope"] = "fixed_horizon"
    manifest["realized_exit_labels_included"] = False
    manifest["realized_exit_label_policy"] = (
        "Realized-PnL labels are excluded from this fixed-horizon training export. "
        "Any future realized-exit export must include exit_policy_version and "
        "position_manager_version and must not mix exit-policy versions without controls."
    )
    manifest["safe_training_targets"] = FIXED_HORIZON_TARGETS
    manifest["future_fixed_horizon_targets_pending_schema"] = FUTURE_FIXED_HORIZON_TARGETS
    manifest["bar_pattern_feature_target_version"] = BAR_PATTERN_FEATURE_TARGET_VERSION
    manifest["advanced_alpha_feature_version"] = ADVANCED_ALPHA_FEATURE_VERSION
    manifest["triple_barrier_target_included"] = True
    manifest["trend_scan_target_included"] = True
    manifest["pit_contract_ok"] = pit_contract.get("ok", False)
    manifest["stale_feature_snapshot_count"] = pit_contract.get(
        "stale_feature_snapshot_count", 0
    )
    manifest["symbol_universe_version"] = SYMBOL_UNIVERSE_VERSION

    labeled_rows = sum(1 for r in rows if r.get("outcome_label") is not None)
    symbols = {r["symbol"] for r in rows if r.get("symbol")}
    statuses = sorted({r.get("label_horizon_status") or "unlabeled" for r in rows})

    return DatasetBuildResult(
        rows=rows,
        source_row_count=len(raw_rows),
        export_row_count=len(rows),
        complete_horizon_rows=complete_horizon_rows,
        labeled_rows=labeled_rows,
        symbols=symbols,
        start_date=config.start_date,
        end_date=config.end_date,
        excluded_reason_counts=exclusion_counts,
        pit_contract=pit_contract,
        pit_coverage=pit_coverage,
        manifest=manifest,
        label_horizon_statuses=statuses,
    )
