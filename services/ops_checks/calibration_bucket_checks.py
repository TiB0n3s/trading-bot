"""Realized calibration bucket operator report."""

from __future__ import annotations

from pathlib import Path

from repositories.lifecycle_analysis_repo import LifecycleAnalysisRepository
from services.calibration_bucket_service import build_calibration_bucket_payload
from services.lifecycle_analysis_service import LifecycleAnalysisService


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def run_calibration_buckets(
    target_date: str,
    *,
    base_dir: Path,
    symbol: str | None = None,
    min_sample_size: int = 5,
    limit: int = 20,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Calibration Buckets - {target_date}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    lifecycle = LifecycleAnalysisService(LifecycleAnalysisRepository(db_path))
    lifecycle_payload = lifecycle.payload(start_date=target_date, symbol=symbol)
    payload = build_calibration_bucket_payload(
        lifecycle_payload.rows,
        min_sample_size=min_sample_size,
    )
    summary = payload.summary
    print(f"report_version          : {summary['report_version']}")
    print(f"runtime_effect          : {summary['runtime_effect']}")
    print(f"rows                    : {summary['rows']}")
    print(f"rows_with_outcome       : {summary['rows_with_outcome']}")
    print(f"missing_outcome_rows    : {summary['missing_outcome_rows']}")
    print(f"bucket_count            : {summary['bucket_count']}")
    print(f"ready_bucket_count      : {summary['ready_bucket_count']}")
    print(f"min_sample_size         : {summary['min_sample_size']}")

    if not summary["rows_with_outcome"]:
        print("[WARN] no lifecycle rows with realized/counterfactual outcomes")
        return False

    print()
    print(
        f"  {'ready':<5} {'n':>5} {'win':>8} {'ev':>8} {'mfe':>8} "
        f"{'mae':>8} {'fp':>6} {'fn':>6} bucket"
    )
    for item in payload.buckets[:limit]:
        print(
            f"  {str(item['ready']):<5} {item['sample_size']:>5} "
            f"{_fmt(item['win_rate']):>8} {_fmt(item['ev_pct']):>8} "
            f"{_fmt(item['mfe_pct']):>8} {_fmt(item['mae_pct']):>8} "
            f"{_fmt(item['false_positive_rate']):>6} "
            f"{_fmt(item['false_negative_rate']):>6} "
            f"{item['bucket']}"
        )

    print()
    print("[OK] calibration bucket report completed")
    return True
