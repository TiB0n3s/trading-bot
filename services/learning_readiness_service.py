"""Holistic readiness scoring for ML/intelligence outcome data.

This service is diagnostic only. It joins existing evidence surfaces so an
operator can see whether the project has enough clean sessions and outcome
coverage for calibration, replay, and future authority promotion work.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


LEARNING_READINESS_REPORT_VERSION = "learning_readiness_v1"
LEARNING_READINESS_RUNTIME_EFFECT = "diagnostic_only_no_live_authority"


@dataclass(frozen=True)
class LearningReadinessPayload:
    summary: dict[str, Any]
    lifecycle: dict[str, Any]
    runtime_health: dict[str, Any]
    candidate_universe: dict[str, Any]
    symbol_patterns: dict[str, Any]
    feature_attribution: dict[str, Any]
    calibration: dict[str, Any]
    blockers: list[str]
    next_actions: list[str]


def _rate(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(count / total, 4)


def _decision_date(row: dict[str, Any]) -> str | None:
    raw = str(row.get("decision_time") or row.get("candidate_ts") or "")
    if len(raw) >= 10:
        return raw[:10]
    return None


def _candidate_summary(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows_list = [dict(row) for row in rows]
    by_status: dict[str, int] = {}
    by_kind: dict[str, int] = {}
    for row in rows_list:
        status = str(row.get("candidate_status") or "unknown")
        kind = str(row.get("candidate_kind") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        by_kind[kind] = by_kind.get(kind, 0) + 1
    return {
        "rows": len(rows_list),
        "scored_rows": sum(1 for row in rows_list if row.get("score") is not None),
        "near_threshold": by_status.get("near_threshold", 0),
        "scored_not_taken": by_status.get("scored_not_taken", 0),
        "taken": by_status.get("taken", 0),
        "exit_considered_not_taken": by_status.get("exit_considered_not_taken", 0),
        "by_status": dict(sorted(by_status.items())),
        "by_kind": dict(sorted(by_kind.items())),
    }


def _stage(*, sessions: int, rows_with_outcome: int, blockers: list[str]) -> str:
    hard_blockers = {
        "missing_runtime_job_runs",
        "missing_lifecycle_rows",
        "missing_outcome_rows",
        "rejected_forward_outcome_coverage_below_80pct",
        "approved_exit_link_rate_below_80pct",
    }
    if any(blocker in hard_blockers for blocker in blockers):
        return "data_plumbing"
    if sessions < 20 or rows_with_outcome < 100:
        return "baseline_collection"
    if sessions < 40 or rows_with_outcome < 250:
        return "baseline_evaluation"
    if sessions < 100 or rows_with_outcome < 750:
        return "promotion_candidate_review"
    return "authority_candidate_review"


def build_learning_readiness_payload(
    *,
    start_date: str,
    end_date: str,
    lifecycle_summary: dict[str, Any],
    lifecycle_rows: Iterable[dict[str, Any]],
    runtime_trend: dict[str, Any] | None = None,
    candidate_rows: Iterable[dict[str, Any]] = (),
    symbol_pattern_summary: dict[str, Any] | None = None,
    feature_summary: dict[str, Any] | None = None,
    feature_guardrails: list[dict[str, Any]] | None = None,
    calibration_summary: dict[str, Any] | None = None,
) -> LearningReadinessPayload:
    rows = [dict(row) for row in lifecycle_rows]
    sessions = len({date for row in rows if (date := _decision_date(row))})
    candidate = _candidate_summary(candidate_rows)
    runtime = runtime_trend or {
        "rows": 0,
        "jobs": [],
        "clean": False,
    }
    pattern_summary = symbol_pattern_summary or {}
    feature_summary = feature_summary or {}
    calibration_summary = calibration_summary or {}
    guardrails = feature_guardrails or []

    approved_rows = (
        int(lifecycle_summary.get("approved_with_exit") or 0)
        + int(lifecycle_summary.get("approved_matched_exit_missing_snapshot") or 0)
        + int(lifecycle_summary.get("approved_open_or_unlinked_exit") or 0)
    )
    rejected_trade_backed = (
        int(lifecycle_summary.get("rejected_with_counterfactual") or 0)
        + int(lifecycle_summary.get("rejected_without_counterfactual") or 0)
    )
    rows_with_outcome = int(pattern_summary.get("rows_with_outcome") or 0)
    if not rows_with_outcome:
        rows_with_outcome = sum(
            1
            for row in rows
            if (
                row.get("approved")
                and row.get("realized_return_pct") is not None
            )
            or (
                not row.get("approved")
                and (
                    row.get("rejected_return_60m") is not None
                    or row.get("rejected_return_30m") is not None
                    or row.get("rejected_return_eod") is not None
                )
            )
        )

    rejected_coverage = lifecycle_summary.get("rejected_counterfactual_coverage_rate")
    approved_exit_rate = lifecycle_summary.get("approved_exit_link_rate")
    blockers: list[str] = []
    if not int(runtime.get("rows") or 0):
        blockers.append("missing_runtime_job_runs")
    elif not runtime.get("clean"):
        blockers.append("runtime_health_not_clean")
    if not int(lifecycle_summary.get("rows") or 0):
        blockers.append("missing_lifecycle_rows")
    if not rows_with_outcome:
        blockers.append("missing_outcome_rows")
    if rejected_trade_backed and (rejected_coverage is None or rejected_coverage < 0.80):
        blockers.append("rejected_forward_outcome_coverage_below_80pct")
    if approved_rows and (approved_exit_rate is None or approved_exit_rate < 0.80):
        blockers.append("approved_exit_link_rate_below_80pct")
    if candidate["rows"] == 0:
        blockers.append("missing_candidate_universe_rows")
    if int(pattern_summary.get("pattern_rows") or 0) == 0 and rows:
        blockers.append("missing_symbol_pattern_rows")
    if int(calibration_summary.get("ready_bucket_count") or 0) == 0 and rows_with_outcome:
        blockers.append("no_ready_calibration_buckets")

    not_ready_features = [
        item
        for item in guardrails
        if item.get("status") == "not_ready"
    ]
    candidate_features = [
        item
        for item in guardrails
        if item.get("status") in {"size_down_candidate", "narrow_block_candidate"}
    ]

    stage = _stage(
        sessions=sessions,
        rows_with_outcome=rows_with_outcome,
        blockers=blockers,
    )
    summary = {
        "report_version": LEARNING_READINESS_REPORT_VERSION,
        "runtime_effect": LEARNING_READINESS_RUNTIME_EFFECT,
        "start_date": start_date,
        "end_date": end_date,
        "readiness_stage": stage,
        "sessions_with_lifecycle_rows": sessions,
        "rows_with_outcome": rows_with_outcome,
        "clean_for_authority_promotion": (
            stage == "authority_candidate_review" and not blockers
        ),
        "authority_note": "diagnostic only; this report cannot approve, size, or execute trades",
    }

    next_actions = []
    if "runtime_health_not_clean" in blockers:
        next_actions.append("run runtime-health/runtime-health-trend and clear failed or launcher-error jobs")
    if "missing_runtime_job_runs" in blockers:
        next_actions.append("confirm scheduled jobs are using job_runner.py and writing job_runs")
    if "missing_outcome_rows" in blockers:
        next_actions.append("wait for or backfill realized/forward outcomes before drawing expectancy conclusions")
    if "rejected_forward_outcome_coverage_below_80pct" in blockers:
        next_actions.append("backfill rejected_signal_outcomes before trusting counterfactual analysis")
    if "approved_exit_link_rate_below_80pct" in blockers:
        next_actions.append("classify open positions versus missing exit snapshot linkage")
    if "missing_candidate_universe_rows" in blockers:
        next_actions.append("verify candidate-universe capture is running with scope=all")
    if "no_ready_calibration_buckets" in blockers:
        next_actions.append("collect more outcomes before using bucket calibration for promotion")
    if not next_actions:
        next_actions.append("review feature candidates manually before any authority wiring")

    return LearningReadinessPayload(
        summary=summary,
        lifecycle={
            "rows": int(lifecycle_summary.get("rows") or 0),
            "approved_rows": approved_rows,
            "approved_exit_link_rate": approved_exit_rate,
            "rejected_trade_backed": rejected_trade_backed,
            "rejected_counterfactual_coverage_rate": rejected_coverage,
            "analysis_ready": bool(lifecycle_summary.get("analysis_ready")),
        },
        runtime_health={
            "job_run_rows": int(runtime.get("rows") or 0),
            "job_count": len(runtime.get("jobs") or []),
            "clean": bool(runtime.get("clean")),
            "failures": sum(int(job.get("failures") or 0) for job in runtime.get("jobs") or []),
            "launcher_errors": sum(int(job.get("launcher_errors") or 0) for job in runtime.get("jobs") or []),
            "lock_skips": sum(int(job.get("lock_skips") or 0) for job in runtime.get("jobs") or []),
            "zero_row_successes": sum(int(job.get("zero_row_successes") or 0) for job in runtime.get("jobs") or []),
            "rows_written": sum(int(job.get("rows_written") or 0) for job in runtime.get("jobs") or []),
        },
        candidate_universe={
            **candidate,
            "candidate_rows_per_lifecycle_row": (
                round(candidate["rows"] / int(lifecycle_summary.get("rows") or 1), 4)
                if lifecycle_summary.get("rows")
                else None
            ),
        },
        symbol_patterns={
            "pattern_rows": int(pattern_summary.get("pattern_rows") or 0),
            "distinct_patterns": int(pattern_summary.get("distinct_patterns") or 0),
            "rows_with_outcome": int(pattern_summary.get("rows_with_outcome") or 0),
        },
        feature_attribution={
            "families": len(guardrails),
            "candidate_features": len(candidate_features),
            "not_ready_features": len(not_ready_features),
            "rows_with_outcome": int(feature_summary.get("rows_with_outcome") or 0),
        },
        calibration={
            "bucket_count": int(calibration_summary.get("bucket_count") or 0),
            "ready_bucket_count": int(calibration_summary.get("ready_bucket_count") or 0),
            "missing_outcome_rows": int(calibration_summary.get("missing_outcome_rows") or 0),
        },
        blockers=blockers,
        next_actions=next_actions,
    )
