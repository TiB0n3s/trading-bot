"""Holistic learning/readiness operator report."""

from __future__ import annotations

import json
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


def _pct(value) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value) * 100:.2f}%"
    except Exception:
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
    full_readiness_target: int = 750,
    report_title: str = "Learning Readiness",
) -> bool:
    end = end_date or start_date
    print()
    print("=" * 72)
    print(f"  {report_title} — {start_date} to {end}")
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
    strategy_memory_path = base_dir / "strategy_memory.json"
    strategy_memory = {}
    if strategy_memory_path.exists():
        try:
            loaded = json.loads(strategy_memory_path.read_text())
            strategy_memory = loaded if isinstance(loaded, dict) else {}
        except Exception:
            strategy_memory = {}

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
        strategy_memory=strategy_memory,
        full_readiness_target=full_readiness_target,
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
    print("Full readiness progress")
    print(
        f"  {'target_integrated_outcomes':<38} "
        f"{payload.progress['full_readiness_integrated_outcome_target']}"
    )
    for key, pct_key in (
        ("outcome_rows", "outcome_rows_pct_of_full"),
        ("pattern_integrated_outcome_rows", "pattern_integrated_pct_of_full"),
        ("momentum_integrated_outcome_rows", "momentum_integrated_pct_of_full"),
        ("prediction_integrated_outcome_rows", "prediction_integrated_pct_of_full"),
        ("fully_integrated_outcome_rows", "fully_integrated_pct_of_full"),
    ):
        print(
            f"  {key:<38} "
            f"{payload.progress[key]:>8} / "
            f"{payload.progress['full_readiness_integrated_outcome_target']:<8} "
            f"{_pct(payload.progress[pct_key]):>8}"
        )
    print(
        f"  {'fully_integrated_rate_of_outcomes':<38} "
        f"{_pct(payload.progress['fully_integrated_rate_of_outcomes'])}"
    )

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
        "rows_with_forward_outcome",
        "missing_forward_outcome",
        "forward_outcome_coverage_rate",
        "non_taken_with_forward_outcome",
        "non_taken_forward_outcome_coverage_rate",
        "candidate_rows_per_lifecycle_row",
    ):
        value = payload.candidate_universe.get(key)
        if key.endswith("_rate"):
            value = _pct(value)
        print(f"  {key:<36} {_fmt(value)}")

    print()
    print("Learning effect")
    for key in (
        "strategy_memory_available",
        "strategy_memory_generated_at",
        "strategy_memory_trade_count",
        "strategy_memory_context_sections",
        "decision_policy_rows",
        "decision_policy_row_rate",
        "decision_policy_block_advisory",
        "decision_policy_size_down_advisory",
        "decision_policy_enforced",
        "decision_policy_block_enforced",
        "decision_policy_size_down_enforced",
        "learning_constrained_rows",
        "learning_observed_not_enforced",
    ):
        print(f"  {key:<36} {_fmt(payload.learning_effect.get(key))}")

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
        print(f"[WARN] {report_title.lower()} has unresolved blockers")
        return False
    print(f"[OK] {report_title.lower()} has no blockers; review manually before promotion")
    return True


def run_learning_effectiveness(
    start_date: str,
    *,
    end_date: str | None,
    base_dir: Path,
    symbol: str | None = None,
    min_feature_sample_size: int = 30,
    min_pattern_sample_size: int = 30,
    min_calibration_sample_size: int = 5,
    full_readiness_target: int = 750,
) -> bool:
    return run_learning_readiness(
        start_date,
        end_date=end_date,
        base_dir=base_dir,
        symbol=symbol,
        min_feature_sample_size=min_feature_sample_size,
        min_pattern_sample_size=min_pattern_sample_size,
        min_calibration_sample_size=min_calibration_sample_size,
        full_readiness_target=full_readiness_target,
        report_title="Learning Effectiveness",
    )
