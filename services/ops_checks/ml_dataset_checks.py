"""Operator checks for canonical ML training dataset exports."""

from __future__ import annotations

import csv
import json
from pathlib import Path
from typing import Any

from ml_platform.dataset_builder import (
    ROW_COLUMNS,
    DatasetBuildConfig,
    DatasetBuildResult,
    build_training_dataset,
)


ML_DATASET_EXPORT_VERSION = "ml_dataset_export_check_v1"


def _pct(numerator: int | float | None, denominator: int | float | None) -> float:
    if not denominator:
        return 0.0
    return round((float(numerator or 0) / float(denominator)) * 100.0, 2)


def _target_counts(rows: list[dict[str, Any]]) -> dict[str, int]:
    targets = (
        "outcome_label",
        "ret_fwd_15m",
        "ret_fwd_30m",
        "triple_barrier_label",
        "trend_scan_label",
    )
    return {
        target: sum(1 for row in rows if row.get(target) is not None)
        for target in targets
    }


def _write_jsonl(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, sort_keys=True, default=str) + "\n")


def _write_csv(path: Path, rows: list[dict[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fieldnames = list(ROW_COLUMNS)
    with path.open("w", newline="", encoding="utf-8") as fh:
        writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        for row in rows:
            writer.writerow({name: row.get(name) for name in fieldnames})


def _write_manifest(path: Path, result: DatasetBuildResult) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(result.manifest, indent=2, sort_keys=True, default=str),
        encoding="utf-8",
    )


def run_ml_dataset_export_check(
    start_date: str,
    *,
    end_date: str | None,
    base_dir: Path,
    output_path: Path | None = None,
    output_format: str = "jsonl",
    include_incomplete: bool = False,
    min_rows: int = 500,
    min_symbols: int = 20,
    max_rows: int | None = 5000,
    full_manifest: bool = False,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Canonical ML Dataset Export - {start_date}..{end_date or start_date}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    try:
        result = build_training_dataset(
            DatasetBuildConfig(
                start_date=start_date,
                end_date=end_date or start_date,
                db_path=db_path,
                include_incomplete_labels=include_incomplete,
                max_source_rows=max_rows,
                build_manifest=bool(output_path and full_manifest),
            )
        )
    except Exception as exc:
        print(f"[WARN] dataset build failed: {type(exc).__name__}: {exc}")
        return False

    target_counts = _target_counts(result.rows)
    rows = result.export_row_count
    source_rows = result.source_row_count
    symbols = len(result.symbols)
    readiness = rows >= min_rows and symbols >= min_symbols and result.pit_contract.get("ok", False)

    written_path = None
    manifest_path = None
    if output_path:
        fmt = output_format.lower().strip()
        if fmt == "csv":
            _write_csv(output_path, result.rows)
        elif fmt == "jsonl":
            _write_jsonl(output_path, result.rows)
        else:
            print(f"[WARN] unsupported output format: {output_format}")
            return False
        written_path = str(output_path)
        manifest_path_obj = output_path.with_suffix(output_path.suffix + ".manifest.json")
        _write_manifest(manifest_path_obj, result)
        manifest_path = str(manifest_path_obj)

    print(f"report_version          : {ML_DATASET_EXPORT_VERSION}")
    print("runtime_effect          : dataset_export_only_no_live_authority")
    print(f"source_rows             : {source_rows}")
    print(f"source_row_limit        : {max_rows or 'none'}")
    print(f"full_manifest          : {full_manifest}")
    print(f"export_rows             : {rows}")
    print(f"complete_horizon_rows   : {result.complete_horizon_rows}")
    print(f"labeled_rows            : {result.labeled_rows}")
    print(f"symbols                 : {symbols}")
    print(f"label_statuses          : {','.join(result.label_horizon_statuses) or '-'}")
    print(f"pit_contract_ok         : {result.pit_contract.get('ok', False)}")
    exact_dates = [
        day
        for day in result.pit_coverage.get("covered_dates", [])
        if day not in set(result.pit_coverage.get("fallback_dates", []))
    ]
    print(f"pit_exact_dates         : {len(exact_dates)}")
    print(f"pit_missing_dates       : {len(result.pit_coverage.get('missing_dates', []))}")
    print(f"excluded_rows           : {json.dumps(result.excluded_reason_counts, sort_keys=True)}")
    for target, count in target_counts.items():
        print(f"{target:<24}: {count} ({_pct(count, rows):.2f}%)")
    print(f"min_rows_required       : {min_rows}")
    print(f"min_symbols_required    : {min_symbols}")
    print(f"training_dataset_ready  : {readiness}")
    if written_path:
        print(f"output_path             : {written_path}")
        print(f"manifest_path           : {manifest_path}")

    if readiness:
        print()
        print("[OK] canonical ML dataset meets configured export floor")
        return True

    print()
    print("[WARN] canonical ML dataset does not yet meet configured export floor")
    return False
