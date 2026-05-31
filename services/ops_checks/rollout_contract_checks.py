"""Rollout contract operator report."""

from __future__ import annotations

from pathlib import Path

from repositories.lifecycle_analysis_repo import LifecycleAnalysisRepository
from services.feature_attribution_service import build_feature_attribution_payload
from services.lifecycle_analysis_service import LifecycleAnalysisService
from services.rollout_contract_service import assess_all_feature_family_rollouts


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def run_rollout_contract_report(
    target_date: str,
    *,
    base_dir: Path,
    symbol: str | None = None,
    min_sample_size: int = 30,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Rollout Contract Report - {target_date}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    lifecycle = LifecycleAnalysisService(LifecycleAnalysisRepository(db_path))
    lifecycle_payload = lifecycle.payload(start_date=target_date, symbol=symbol)
    attribution = build_feature_attribution_payload(
        lifecycle_payload.rows,
        min_sample_size=min_sample_size,
    )
    if not attribution.summary["rows_with_outcome"]:
        print(f"report_version          : rollout_contract_v1")
        print(f"rows_with_outcome       : 0")
        print("[WARN] no lifecycle rows with realized/counterfactual outcomes")
        return False

    payload = assess_all_feature_family_rollouts(
        attribution_payload=attribution,
        decision_date=target_date,
        review_window_start=target_date,
        review_window_end=target_date,
    )

    print(f"report_version          : {payload.report_version}")
    print(f"decision_date           : {payload.decision_date}")
    print(f"feature_families        : {len(payload.assessments)}")
    print(f"runtime_effect          : telemetry_only_no_live_authority")
    print()
    print(
        f"  {'family':<26} {'status':<24} {'sample':>7} "
        f"{'missing':>8} {'stable':>8} {'overlap':>8} {'fp_red':>8} {'fn_cost':>8}"
    )
    for assessment in payload.assessments:
        print(
            f"  {assessment.feature_family:<26} "
            f"{assessment.status.value:<24} "
            f"{assessment.sample_size:>7} "
            f"{_fmt(assessment.missing_rate):>8} "
            f"{_fmt(assessment.stability_share):>8} "
            f"{_fmt(assessment.overlap_risk):>8} "
            f"{_fmt(assessment.false_positive_reduction):>8} "
            f"{_fmt(assessment.false_negative_cost):>8}"
        )
        if assessment.guardrail_failures:
            print(f"    capped_by: {', '.join(assessment.guardrail_failures)}")
        if assessment.promotion_reasons:
            print(f"    reasons  : {', '.join(assessment.promotion_reasons)}")
        print(f"    actions  : {assessment.restrictions.get('allowed_actions')}")

    print()
    print("[OK] rollout contract report completed; no live authority changed")
    return True
