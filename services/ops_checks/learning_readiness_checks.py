"""Holistic learning/readiness operator report."""

from __future__ import annotations

from pathlib import Path

from repositories.candidate_universe_repo import CandidateUniverseRepository
from repositories.job_runs_repo import JobRunsRepository
from repositories.lifecycle_analysis_repo import LifecycleAnalysisRepository
from services.calibration_bucket_service import build_calibration_bucket_payload
from services.feature_attribution_service import build_feature_attribution_payload
from services.job_runs_service import JobRunsService
from services.learning_readiness_service import build_learning_readiness_payload
from services.lifecycle_analysis_service import LifecycleAnalysisService
from services.symbol_pattern_outcome_service import build_symbol_pattern_outcome_payload


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def run_learning_readiness(
    start_date: str,
    *,
    end_date: str | None,
    base_dir: Path,
    symbol: str | None = None,
    min_feature_sample_size: int = 30,
    min_pattern_sample_size: int = 30,
    min_calibration_sample_size: int = 5,
) -> bool:
    end = end_date or start_date
    print()
    print("=" * 72)
    print(f"  Learning Readiness — {start_date} to {end}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    lifecycle = LifecycleAnalysisService(LifecycleAnalysisRepository(db_path))
    lifecycle_payload = lifecycle.payload(
        start_date=start_date,
        end_date=end,
        symbol=symbol,
    )
    rows = lifecycle_payload.rows

    runtime_trend = JobRunsService(JobRunsRepository(db_path)).trend_payload(
        start_date=start_date,
        end_date=end,
    )
    candidate_rows = [
        dict(row)
        for row in CandidateUniverseRepository(db_path).rows_between(
            start_date,
            end,
            symbol=symbol,
        )
    ]
    pattern_payload = build_symbol_pattern_outcome_payload(
        rows,
        min_sample_size=min_pattern_sample_size,
    )
    feature_payload = build_feature_attribution_payload(
        rows,
        min_sample_size=min_feature_sample_size,
        rolling_window_size=50,
    )
    calibration_payload = build_calibration_bucket_payload(
        rows,
        min_sample_size=min_calibration_sample_size,
    )
    payload = build_learning_readiness_payload(
        start_date=start_date,
        end_date=end,
        lifecycle_summary=lifecycle_payload.summary,
        lifecycle_rows=rows,
        runtime_trend=runtime_trend,
        candidate_rows=candidate_rows,
        symbol_pattern_summary=pattern_payload.summary,
        feature_summary=feature_payload.summary,
        feature_guardrails=feature_payload.rollout_guardrails,
        calibration_summary=calibration_payload.summary,
    )

    summary = payload.summary
    print(f"report_version                : {summary['report_version']}")
    print(f"runtime_effect                : {summary['runtime_effect']}")
    print(f"readiness_stage               : {summary['readiness_stage']}")
    print(f"sessions_with_lifecycle_rows  : {summary['sessions_with_lifecycle_rows']}")
    print(f"rows_with_outcome             : {summary['rows_with_outcome']}")
    print(f"clean_for_authority_promotion : {summary['clean_for_authority_promotion']}")
    print(f"authority_note                : {summary['authority_note']}")
    if symbol:
        print(f"symbol                        : {symbol.upper()}")

    print()
    print("Runtime health")
    for key, value in payload.runtime_health.items():
        print(f"  {key:<28} {_fmt(value)}")

    print()
    print("Lifecycle coverage")
    for key, value in payload.lifecycle.items():
        print(f"  {key:<36} {_fmt(value)}")

    print()
    print("Candidate universe")
    for key in (
        "rows",
        "scored_rows",
        "taken",
        "near_threshold",
        "scored_not_taken",
        "exit_considered_not_taken",
        "candidate_rows_per_lifecycle_row",
    ):
        print(f"  {key:<36} {_fmt(payload.candidate_universe.get(key))}")

    print()
    print("Intelligence diagnostics")
    print(
        f"  {'symbol_patterns':<28} "
        f"rows={payload.symbol_patterns['pattern_rows']} "
        f"distinct={payload.symbol_patterns['distinct_patterns']} "
        f"outcomes={payload.symbol_patterns['rows_with_outcome']}"
    )
    print(
        f"  {'feature_attribution':<28} "
        f"families={payload.feature_attribution['families']} "
        f"candidates={payload.feature_attribution['candidate_features']} "
        f"not_ready={payload.feature_attribution['not_ready_features']}"
    )
    print(
        f"  {'calibration':<28} "
        f"buckets={payload.calibration['bucket_count']} "
        f"ready={payload.calibration['ready_bucket_count']} "
        f"missing_outcomes={payload.calibration['missing_outcome_rows']}"
    )

    if payload.blockers:
        print()
        print("Blockers")
        for blocker in payload.blockers:
            print(f"  - {blocker}")

    print()
    print("Next actions")
    for action in payload.next_actions:
        print(f"  - {action}")

    print()
    if payload.blockers:
        print("[WARN] learning readiness has unresolved blockers")
        return False
    print("[OK] learning readiness has no blockers; review manually before promotion")
    return True
