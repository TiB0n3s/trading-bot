#!/usr/bin/env python3
"""
Export a read-only ML research dataset from trades.db.

This script reads feature_snapshots and optional labels/context/predictions.
It does not train models, write to SQLite, place orders, or affect runtime
behavior.

By default, exports are training-safe fixed-horizon rows only: incomplete,
unlabeled, and near-close partial label rows are excluded from the CSV and
counted in the manifest.

Usage:
  python3 export_ml_dataset.py --date 2026-05-26 --output /tmp/ml_dataset.csv
  python3 export_ml_dataset.py --start-date 2026-05-20 --end-date 2026-05-26 --output /tmp/ml_dataset.csv
"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path
from typing import Any, Callable

from repositories.ml_export_repo import MlExportRepository

from ml_platform.governance import build_dataset_manifest
from ml_platform.pit_context import get_archive_root, pit_coverage_for_range

BASE_COLUMNS = [
    "snapshot_id",
    "snapshot_date",
    "timestamp",
    "symbol",
    "last_price",
    "ret_1m",
    "ret_5m",
    "ret_15m",
    "range_pos_15m",
    "distance_from_5m_high",
    "distance_from_5m_low",
    "distance_from_vwap",
    "volume_ratio_5m",
    "benchmark_symbol",
    "benchmark_ret_5m",
    "relative_strength_5m",
    "spread_pct",
    "market_session",
    "macro_regime",
    "market_bias",
    "trend_direction",
    "trend_strength",
    "feature_available_at",
    "feature_generated_at",
    "feature_age_seconds",
    "source",
    "is_stale",
    "staleness_reason",
    "bar_timeframe",
    "bar_count",
    "setup_label",
    "setup_recommendation",
    "setup_score",
    "setup_confidence",
    "setup_key",
    "bar_pattern_feature_version",
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
    "future_price_5m",
    "future_price_15m",
    "future_price_30m",
    "future_price_60m",
    "ret_fwd_5m",
    "ret_fwd_15m",
    "ret_fwd_30m",
    "ret_fwd_60m",
    "max_up_15m",
    "max_down_15m",
    "max_up_60m",
    "max_down_60m",
    "action_direction",
    "action_mfe_60m_pct",
    "action_mae_60m_pct",
    "outcome_label",
    "triple_barrier_label",
    "triple_barrier_reason",
    "triple_barrier_bars_to_event",
    "triple_barrier_profit_pct",
    "triple_barrier_stop_pct",
    "context_bias",
    "context_confidence",
    "context_risk_level",
    "context_entry_quality",
    "context_catalyst_score",
    "context_relative_strength_score",
    "context_sector_alignment",
    "context_index_alignment",
    "prediction_score",
    "probability_of_profit",
    "probability_of_order",
    "expected_pnl",
    "prediction_confidence",
    "prediction_sample_size",
    "label_horizon_status",
    "label_target_family",
    "realized_exit_label_status",
    "realized_exit_label_version",
    "exit_policy_version",
    "position_manager_version",
    "canonical_exit_version",
]

FIXED_HORIZON_TARGETS = [
    "ret_fwd_15m",
    "ret_fwd_30m",
    "ret_fwd_60m",
    "max_up_15m",
    "max_down_15m",
    "max_up_60m",
    "max_down_60m",
    "action_mfe_60m_pct",
    "action_mae_60m_pct",
    "triple_barrier_label",
    "trend_scan_label",
]

FUTURE_FIXED_HORIZON_TARGETS = [
    "max_favorable_excursion",
    "max_adverse_excursion",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Single snapshot date, YYYY-MM-DD")
    parser.add_argument("--start-date", help="Start snapshot date, YYYY-MM-DD")
    parser.add_argument("--end-date", help="End snapshot date, YYYY-MM-DD")
    parser.add_argument("--output", required=True, help="CSV output path")
    parser.add_argument(
        "--db-path",
        default=str(Path(__file__).resolve().parent / "trades.db"),
        help="SQLite DB path",
    )
    parser.add_argument("--manifest-output", help="Optional JSON dataset manifest output path")
    parser.add_argument("--query-version", default="ml_dataset_export_v1")
    parser.add_argument("--label-version", default="label_taxonomy_v1")
    parser.add_argument(
        "--include-incomplete-labels",
        action="store_true",
        help="Include unlabeled/partial/incomplete rows. Default excludes them for training safety.",
    )
    parser.add_argument(
        "--label-scope",
        choices=("fixed_horizon", "audit_all"),
        default="fixed_horizon",
        help="Default fixed_horizon keeps realized-PnL labels out of the export surface.",
    )
    parser.add_argument("--chunk-size", type=int, default=1000)
    args = parser.parse_args()

    if args.date and (args.start_date or args.end_date):
        parser.error("Use either --date or --start-date/--end-date, not both")
    if not args.date and not (args.start_date and args.end_date):
        parser.error("Provide --date or both --start-date and --end-date")

    return args


def date_filter(args: argparse.Namespace) -> tuple[str, tuple[str, ...]]:
    if args.date:
        return "substr(fs.timestamp, 1, 10) = ?", (args.date,)
    return "substr(fs.timestamp, 1, 10) BETWEEN ? AND ?", (args.start_date, args.end_date)


def fetch_rows(args: argparse.Namespace) -> list:
    db_path = Path(args.db_path)
    where_sql, params = date_filter(args)
    return MlExportRepository(db_path).fetch_rows(where_sql, params)


def stream_rows(args: argparse.Namespace, row_callback: Callable[[Any], None]) -> None:
    db_path = Path(args.db_path)
    where_sql, params = date_filter(args)
    MlExportRepository(db_path).fetch_rows(
        where_sql,
        params,
        row_callback=row_callback,
        chunk_size=args.chunk_size,
    )


def write_csv(rows: list, output: str) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BASE_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row[col] for col in BASE_COLUMNS})

    return path


def _exclusion_counts(rows: list) -> dict[str, int]:
    counts: dict[str, int] = {}
    for r in rows:
        status = r["label_horizon_status"] or "unlabeled"
        if status != "complete":
            counts[status] = counts.get(status, 0) + 1
    return counts


def training_rows(rows: list, include_incomplete_labels: bool) -> list:
    if include_incomplete_labels:
        return rows
    return [r for r in rows if (r["label_horizon_status"] or "unlabeled") == "complete"]


def _status(row: Any) -> str:
    return row["label_horizon_status"] or "unlabeled"


def _include_row(row: Any, include_incomplete_labels: bool) -> bool:
    return include_incomplete_labels or _status(row) == "complete"


def write_csv_streaming(args: argparse.Namespace) -> tuple[Path, dict[str, Any]]:
    path = Path(args.output)
    path.parent.mkdir(parents=True, exist_ok=True)
    stats: dict[str, Any] = {
        "source_rows": 0,
        "export_rows": 0,
        "complete_horizon_rows": 0,
        "labeled_rows": 0,
        "symbols": set(),
        "included_label_horizon_statuses": set(),
        "exclusion_counts": {},
    }

    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BASE_COLUMNS)
        writer.writeheader()

        def handle_row(row: Any) -> None:
            stats["source_rows"] += 1
            status = _status(row)
            if status == "complete":
                stats["complete_horizon_rows"] += 1
            else:
                counts = stats["exclusion_counts"]
                counts[status] = counts.get(status, 0) + 1
            if not _include_row(row, args.include_incomplete_labels):
                return
            writer.writerow({col: row[col] for col in BASE_COLUMNS})
            stats["export_rows"] += 1
            if row["outcome_label"] is not None:
                stats["labeled_rows"] += 1
            stats["symbols"].add(row["symbol"])
            stats["included_label_horizon_statuses"].add(status)

        stream_rows(args, handle_row)

    stats["symbols"] = sorted(stats["symbols"])
    stats["included_label_horizon_statuses"] = sorted(stats["included_label_horizon_statuses"])
    return path, stats


def main() -> int:
    args = parse_args()
    path, stats = write_csv_streaming(args)
    exclusion_counts = stats["exclusion_counts"]
    manifest_path = None
    if args.manifest_output:
        _start = args.date or args.start_date
        _end = args.date or args.end_date
        pit_cov = (
            pit_coverage_for_range(
                _start,
                _end,
                archive_root=get_archive_root(Path(args.db_path).parent),
            )
            if _start and _end
            else None
        )
        manifest = build_dataset_manifest(
            db_path=args.db_path,
            start_date=_start,
            end_date=_end,
            query_version=args.query_version,
            label_version=args.label_version,
            excluded_rows_reason_counts=exclusion_counts,
            pit_coverage=pit_cov,
        )
        manifest["source_row_count"] = manifest.get("row_count")
        manifest["export_row_count"] = stats["export_rows"]
        manifest["complete_horizon_rows"] = stats["complete_horizon_rows"]
        manifest["training_default_complete_horizon_only"] = not args.include_incomplete_labels
        manifest["included_label_horizon_statuses"] = stats["included_label_horizon_statuses"]
        manifest["streaming_export_chunk_size"] = args.chunk_size
        manifest["label_scope"] = args.label_scope
        manifest["realized_exit_labels_included"] = False
        manifest["realized_exit_label_policy"] = (
            "Realized-PnL labels are excluded from this fixed-horizon training export. "
            "Any realized-exit audit surface must include realized_exit_label_version, "
            "exit_policy_version, and position_manager_version and must not mix "
            "exit-policy versions without controls."
        )
        manifest["safe_training_targets"] = FIXED_HORIZON_TARGETS
        manifest["future_fixed_horizon_targets_pending_schema"] = FUTURE_FIXED_HORIZON_TARGETS
        manifest_path = Path(args.manifest_output)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    print("=== ML dataset export ===")
    print(f"output       : {path}")
    print(f"source_rows  : {stats['source_rows']}")
    print(f"export_rows  : {stats['export_rows']}")
    print(f"labeled_rows : {stats['labeled_rows']}")
    print(f"symbols      : {len(stats['symbols'])}")
    print(f"label_scope  : {args.label_scope}")
    print(f"complete_only: {not args.include_incomplete_labels}")
    for reason, n in sorted(exclusion_counts.items()):
        print(f"  {reason:<28} {n}")
    if manifest_path:
        print(f"manifest     : {manifest_path}")

    if not stats["source_rows"]:
        print("[WARN] no feature_snapshots matched the requested date range")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
