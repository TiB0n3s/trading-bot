"""Operator report for holistic decision quality review."""

from __future__ import annotations

from pathlib import Path

from repositories.lifecycle_analysis_repo import LifecycleAnalysisRepository
from services.decision_quality_review_service import (
    build_decision_quality_review_payload,
)
from services.lifecycle_analysis_service import LifecycleAnalysisService


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def run_decision_quality_review(
    target_date: str,
    *,
    base_dir: Path,
    symbol: str | None = None,
    samples: int = 20,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Decision Quality Review - {target_date}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    lifecycle = LifecycleAnalysisService(LifecycleAnalysisRepository(db_path))
    lifecycle_payload = lifecycle.payload(start_date=target_date, symbol=symbol)
    payload = build_decision_quality_review_payload(
        lifecycle_payload.rows,
        samples=samples,
    )

    for key, value in payload.summary.items():
        print(f"{key:<40}: {value}")

    if not payload.summary["rows"]:
        print("[WARN] no lifecycle rows found")
        return False

    print()
    print("Quality labels")
    for item in payload.quality_counts:
        print(f"  {item['bucket']:<38} {item['count']:>6}")

    print()
    print("Learning actions")
    for item in payload.learning_action_counts:
        print(f"  {item['bucket']:<38} {item['count']:>6}")

    print()
    print("Priority review rows")
    print(
        f"  {'time':<19} {'sym':<6} {'quality':<32} {'ret':>8} {'mfe':>8} "
        f"{'capture':>8} {'setup':<18} {'pattern':<24} reason"
    )
    for row in payload.rows:
        print(
            f"  {str(row.get('decision_time') or '-')[:19]:<19} "
            f"{str(row.get('symbol') or '-'):<6} "
            f"{str(row.get('quality_label') or '-')[:32]:<32} "
            f"{_fmt(row.get('outcome_return_pct')):>8} "
            f"{_fmt(row.get('mfe_pct')):>8} "
            f"{_fmt(row.get('capture_ratio')):>8} "
            f"{str(row.get('setup_label') or '-')[:18]:<18} "
            f"{str(row.get('symbol_pattern') or '-')[:24]:<24} "
            f"{row.get('quality_reason') or '-'}"
        )

    print()
    if payload.summary["analysis_ready"]:
        print("[OK] decision quality review completed")
    else:
        print("[WARN] decision quality review has outcome coverage gaps")
    return True
