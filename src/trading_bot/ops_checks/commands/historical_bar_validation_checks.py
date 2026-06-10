"""Bucket validation for historical-bar pattern learning labels."""

from __future__ import annotations

from collections import defaultdict
from pathlib import Path
from typing import Any, Iterable

from repositories.historical_bar_training_repo import fetch_historical_bar_training_rows

HISTORICAL_BAR_VALIDATION_VERSION = "historical_bar_validation_buckets_v1"


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except Exception:
        return None


def _session_phase(row: dict[str, Any]) -> str:
    minute = _int(row.get("minute_of_day"))
    if minute is None:
        return "unknown"
    if minute < 10 * 60:
        return "open"
    if minute < 11 * 60 + 30:
        return "morning"
    if minute < 14 * 60:
        return "midday"
    if minute < 15 * 60 + 30:
        return "afternoon"
    return "power_hour"


def _bucket_numeric(value: Any, *, low: float, high: float, labels: tuple[str, str, str]) -> str:
    number = _float(value)
    if number is None:
        return "unknown"
    if number < low:
        return labels[0]
    if number > high:
        return labels[2]
    return labels[1]


def _label_value(row: dict[str, Any], label_target: str) -> int | None:
    return _int(row.get(label_target))


def _bucket_rows(
    rows: Iterable[dict[str, Any]],
    *,
    label_target: str,
    bucket_name: str,
    bucket_fn,
) -> list[dict[str, Any]]:
    groups: dict[str, list[int]] = defaultdict(list)
    for row in rows:
        label = _label_value(row, label_target)
        if label is None:
            continue
        groups[str(bucket_fn(row))].append(label)
    output: list[dict[str, Any]] = []
    for bucket, labels in groups.items():
        total = len(labels)
        positive = sum(1 for value in labels if value > 0)
        negative = sum(1 for value in labels if value < 0)
        timeout = sum(1 for value in labels if value == 0)
        output.append(
            {
                "bucket_family": bucket_name,
                "bucket": bucket,
                "rows": total,
                "positive_rate": round(positive / total, 4) if total else 0.0,
                "negative_rate": round(negative / total, 4) if total else 0.0,
                "timeout_rate": round(timeout / total, 4) if total else 0.0,
            }
        )
    output.sort(key=lambda item: (-int(item["rows"]), item["bucket_family"], item["bucket"]))
    return output


def build_historical_bar_validation_payload(
    *,
    db_path: Path,
    start_date: str,
    end_date: str,
    label_target: str,
    rows_per_symbol: int,
    limit: int,
    min_bucket_rows: int = 50,
) -> dict[str, Any]:
    rows = fetch_historical_bar_training_rows(
        db_path=db_path,
        start_date=start_date,
        end_date=end_date,
        label_target=label_target,
        rows_per_symbol=rows_per_symbol,
        limit=limit,
    )
    bucket_specs = [
        ("symbol", lambda row: row.get("symbol") or "unknown"),
        ("session_phase", _session_phase),
        (
            "volatility",
            lambda row: _bucket_numeric(
                row.get("rolling_volatility_20_pct"),
                low=0.05,
                high=0.25,
                labels=("low_vol", "normal_vol", "high_vol"),
            ),
        ),
        (
            "vpin_toxicity",
            lambda row: _bucket_numeric(
                row.get("vpin_toxicity_20"),
                low=0.25,
                high=0.65,
                labels=("low_toxicity", "normal_toxicity", "high_toxicity"),
            ),
        ),
        (
            "cvd_alignment",
            lambda row: _bucket_numeric(
                row.get("cvd_price_corr_20"),
                low=-0.1,
                high=0.3,
                labels=("cvd_divergent", "cvd_mixed", "cvd_confirming"),
            ),
        ),
        (
            "fractional_memory",
            lambda row: _bucket_numeric(
                row.get("fractional_diff_zscore_20"),
                low=-1.0,
                high=1.0,
                labels=("memory_negative", "memory_neutral", "memory_positive"),
            ),
        ),
    ]
    buckets: list[dict[str, Any]] = []
    for bucket_name, bucket_fn in bucket_specs:
        buckets.extend(
            row
            for row in _bucket_rows(
                rows,
                label_target=label_target,
                bucket_name=bucket_name,
                bucket_fn=bucket_fn,
            )
            if int(row["rows"]) >= min_bucket_rows
        )
    labels = [_label_value(row, label_target) for row in rows]
    labels = [label for label in labels if label is not None]
    return {
        "report_version": HISTORICAL_BAR_VALIDATION_VERSION,
        "runtime_effect": "validation_only_no_live_authority",
        "start_date": start_date,
        "end_date": end_date,
        "label_target": label_target,
        "rows_loaded": len(rows),
        "rows_per_symbol": rows_per_symbol,
        "symbol_count": len({row.get("symbol") for row in rows if row.get("symbol")}),
        "label_counts": {
            "-1": sum(1 for label in labels if label < 0),
            "0": sum(1 for label in labels if label == 0),
            "1": sum(1 for label in labels if label > 0),
        },
        "bucket_rows": buckets,
        "min_bucket_rows": min_bucket_rows,
    }


def run_historical_bar_validation(
    *,
    base_dir: Path,
    start_date: str,
    end_date: str,
    label_target: str = "triple_barrier_label",
    rows_per_symbol: int = 250,
    limit: int = 20000,
    min_bucket_rows: int = 50,
    print_limit: int = 30,
) -> bool:
    payload = build_historical_bar_validation_payload(
        db_path=base_dir / "trades.db",
        start_date=start_date,
        end_date=end_date,
        label_target=label_target,
        rows_per_symbol=rows_per_symbol,
        limit=limit,
        min_bucket_rows=min_bucket_rows,
    )
    print()
    print("=" * 72)
    print("  Historical Bar Validation Buckets")
    print("=" * 72)
    print(f"report_version          : {payload['report_version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"date_filter             : {start_date}..{end_date}")
    print(f"label_target            : {label_target}")
    print(f"rows_loaded             : {payload['rows_loaded']}")
    print(f"rows_per_symbol         : {rows_per_symbol}")
    print(f"symbol_count            : {payload['symbol_count']}")
    print(f"label_counts            : {payload['label_counts']}")
    print(f"min_bucket_rows         : {min_bucket_rows}")
    print()
    print("Buckets")
    for row in payload["bucket_rows"][:print_limit]:
        print(
            f"  {row['bucket_family']:<20} {row['bucket']:<24} "
            f"rows={row['rows']:<6} pos={row['positive_rate']:<6.3f} "
            f"neg={row['negative_rate']:<6.3f} timeout={row['timeout_rate']:<6.3f}"
        )
    ok = payload["rows_loaded"] > 0 and payload["symbol_count"] > 0
    print()
    if ok:
        print("[OK] historical-bar validation buckets generated")
        return True
    print("[WARN] no historical-bar validation rows available")
    return False
