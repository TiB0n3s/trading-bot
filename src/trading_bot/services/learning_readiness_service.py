"""Holistic readiness scoring for ML/intelligence outcome data.

This service is diagnostic only. It joins existing evidence surfaces so an
operator can see whether the project has enough clean sessions and outcome
coverage for calibration, replay, and future authority promotion work.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from services.intelligence.candidates.outcome_coverage import summarize_candidate_outcome_coverage

LEARNING_READINESS_REPORT_VERSION = "learning_readiness_v1"
LEARNING_READINESS_RUNTIME_EFFECT = "diagnostic_only_no_live_authority"
DEFAULT_FULL_READINESS_INTEGRATED_OUTCOME_TARGET = 750


@dataclass(frozen=True)
class LearningReadinessPayload:
    summary: dict[str, Any]
    lifecycle: dict[str, Any]
    runtime_health: dict[str, Any]
    candidate_universe: dict[str, Any]
    learning_effect: dict[str, Any]
    symbol_patterns: dict[str, Any]
    feature_attribution: dict[str, Any]
    calibration: dict[str, Any]
    progress: dict[str, Any]
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
    coverage = summarize_candidate_outcome_coverage(rows_list)
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
        "rows_with_forward_outcome": coverage["rows_with_forward_outcome"],
        "missing_forward_outcome": coverage["missing_forward_outcome"],
        "forward_outcome_coverage_rate": coverage["forward_outcome_coverage_rate"],
        "non_taken_rows": coverage["non_taken_rows"],
        "non_taken_with_forward_outcome": coverage["non_taken_with_forward_outcome"],
        "non_taken_forward_outcome_coverage_rate": coverage[
            "non_taken_forward_outcome_coverage_rate"
        ],
    }


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _outcome(row: dict[str, Any]) -> float | None:
    if row.get("approved"):
        return _float(row.get("realized_return_pct"))
    return _float(
        row.get("rejected_return_60m")
        or row.get("rejected_return_30m")
        or row.get("rejected_return_eod")
    )


def _canonical(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("canonical_intelligence_json")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        loaded = json.loads(str(raw))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _path(data: dict[str, Any], *keys: str) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _meaningful(value: Any, *, default_values: set[str] | None = None) -> bool:
    if value is None or value == "":
        return False
    text = str(value).strip().lower()
    defaults = default_values or {"unknown", "none", "not_applicable"}
    return text not in defaults


def _integrated_outcome_progress(
    rows: Iterable[dict[str, Any]],
    *,
    full_readiness_target: int,
) -> dict[str, Any]:
    rows_with_outcome = [dict(row) for row in rows if _outcome(dict(row)) is not None]
    pattern_defaults = {
        "unknown",
        "mixed_or_unclassified_pattern",
        "unclassified",
        "none",
    }
    momentum_defaults = {
        "unknown",
        "insufficient_data",
        "not_applicable",
        "none",
    }
    prediction_defaults = {
        "unknown",
        "not_applicable",
        "none",
        "no_prediction",
    }

    pattern_rows = 0
    momentum_rows = 0
    prediction_rows = 0
    fully_integrated = 0
    for row in rows_with_outcome:
        canonical = _canonical(row)
        pattern_value = row.get("symbol_pattern") or _path(
            canonical, "pattern_state", "pattern_label"
        )
        has_pattern = _meaningful(pattern_value, default_values=pattern_defaults)
        momentum_values = [
            _path(canonical, "momentum_state", "session_label"),
            _path(canonical, "momentum_state", "state"),
            _path(canonical, "momentum_state", "direction"),
            row.get("session_trend_label"),
        ]
        has_momentum = any(
            _meaningful(value, default_values=momentum_defaults) for value in momentum_values
        )
        prediction_values = [
            _path(canonical, "prediction_state", "ml_bucket"),
            _path(canonical, "prediction_state", "ml_score"),
            _path(canonical, "prediction_state", "deterministic_decision"),
            _path(canonical, "prediction_state", "deterministic_score"),
            row.get("ml_prediction_bucket"),
            row.get("prediction_score"),
        ]
        has_prediction = any(
            _meaningful(value, default_values=prediction_defaults) for value in prediction_values
        )
        if has_pattern:
            pattern_rows += 1
        if has_momentum:
            momentum_rows += 1
        if has_prediction:
            prediction_rows += 1
        if has_pattern and has_momentum and has_prediction:
            fully_integrated += 1

    target = max(1, int(full_readiness_target or 1))
    return {
        "full_readiness_integrated_outcome_target": target,
        "outcome_rows": len(rows_with_outcome),
        "pattern_integrated_outcome_rows": pattern_rows,
        "momentum_integrated_outcome_rows": momentum_rows,
        "prediction_integrated_outcome_rows": prediction_rows,
        "fully_integrated_outcome_rows": fully_integrated,
        "outcome_rows_pct_of_full": min(1.0, round(len(rows_with_outcome) / target, 4)),
        "pattern_integrated_pct_of_full": min(1.0, round(pattern_rows / target, 4)),
        "momentum_integrated_pct_of_full": min(1.0, round(momentum_rows / target, 4)),
        "prediction_integrated_pct_of_full": min(1.0, round(prediction_rows / target, 4)),
        "fully_integrated_pct_of_full": min(1.0, round(fully_integrated / target, 4)),
        "fully_integrated_rate_of_outcomes": _rate(
            fully_integrated,
            len(rows_with_outcome),
        ),
    }


def _learning_effect_summary(
    rows: Iterable[dict[str, Any]],
    *,
    strategy_memory: dict[str, Any] | None = None,
) -> dict[str, Any]:
    rows_list = [dict(row) for row in rows]
    dp_rows = 0
    block_advisory = 0
    size_down_advisory = 0
    enforced = 0
    block_enforced = 0
    size_down_enforced = 0
    observed_not_enforced = 0

    for row in rows_list:
        canonical = _canonical(row)
        outcome = _path(
            canonical,
            "advisory_authority_state",
            "decision_policy_outcome",
        )
        if not isinstance(outcome, dict):
            outcome = {}
        advisory = str(outcome.get("advisory_decision") or "").strip().lower()
        if not advisory:
            continue
        dp_rows += 1
        is_block = advisory == "block"
        is_size_down = advisory == "size_down"
        is_enforced = bool(outcome.get("enforced"))
        effect_on_execution = str(outcome.get("effect_on_execution") or "")
        effect_on_size = str(outcome.get("effect_on_size") or "")

        if is_block:
            block_advisory += 1
        if is_size_down:
            size_down_advisory += 1
        if is_enforced:
            enforced += 1
        if is_enforced and is_block and effect_on_execution == "block":
            block_enforced += 1
        if is_enforced and is_size_down and effect_on_size in {"size_down", "cap"}:
            size_down_enforced += 1
        if (is_block or is_size_down) and not is_enforced:
            observed_not_enforced += 1

    memory = strategy_memory if isinstance(strategy_memory, dict) else {}
    context_sections = (
        "setup_label_context",
        "prediction_decision_context",
        "buy_opportunity_context",
        "session_trend_context",
        "symbol_setup_label_context",
        "symbol_prediction_context",
        "symbol_buy_opportunity_context",
        "symbol_session_trend_context",
    )
    nonempty_context_sections = sum(1 for section in context_sections if memory.get(section))
    return {
        "strategy_memory_available": bool(memory),
        "strategy_memory_generated_at": memory.get("generated_at"),
        "strategy_memory_trade_count": int(memory.get("trade_count") or 0),
        "strategy_memory_context_sections": nonempty_context_sections,
        "decision_policy_rows": dp_rows,
        "decision_policy_row_rate": _rate(dp_rows, len(rows_list)),
        "decision_policy_block_advisory": block_advisory,
        "decision_policy_size_down_advisory": size_down_advisory,
        "decision_policy_enforced": enforced,
        "decision_policy_block_enforced": block_enforced,
        "decision_policy_size_down_enforced": size_down_enforced,
        "learning_constrained_rows": block_enforced + size_down_enforced,
        "learning_observed_not_enforced": observed_not_enforced,
    }


def _stage(*, sessions: int, rows_with_outcome: int, blockers: list[str]) -> str:
    hard_blockers = {
        "missing_runtime_job_runs",
        "missing_lifecycle_rows",
        "missing_outcome_rows",
        "rejected_forward_outcome_coverage_below_80pct",
        "approved_exit_outcome_coverage_below_80pct",
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
    strategy_memory: dict[str, Any] | None = None,
    full_readiness_target: int = DEFAULT_FULL_READINESS_INTEGRATED_OUTCOME_TARGET,
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
    rejected_trade_backed = int(lifecycle_summary.get("rejected_with_counterfactual") or 0) + int(
        lifecycle_summary.get("rejected_without_counterfactual") or 0
    )
    rows_with_outcome = int(pattern_summary.get("rows_with_outcome") or 0)
    if not rows_with_outcome:
        rows_with_outcome = sum(1 for row in rows if _outcome(row) is not None)
    progress = _integrated_outcome_progress(
        rows,
        full_readiness_target=full_readiness_target,
    )
    learning_effect = _learning_effect_summary(
        rows,
        strategy_memory=strategy_memory,
    )

    rejected_coverage = lifecycle_summary.get("rejected_counterfactual_coverage_rate")
    approved_exit_rate = lifecycle_summary.get("approved_exit_link_rate")
    approved_matched_exit_rate = lifecycle_summary.get("approved_matched_exit_coverage_rate")
    approved_exit_outcome_rate = (
        approved_matched_exit_rate if approved_matched_exit_rate is not None else approved_exit_rate
    )
    blockers: list[str] = []
    if not int(runtime.get("rows") or 0):
        blockers.append("missing_runtime_job_runs")
    elif not runtime.get("clean"):
        blockers.append("runtime_health_not_clean")
    lifecycle_row_count = int(lifecycle_summary.get("rows") or 0)
    if not lifecycle_row_count:
        blockers.append("missing_lifecycle_rows")
    if lifecycle_row_count and not rows_with_outcome:
        blockers.append("missing_outcome_rows")
    if rejected_trade_backed and (rejected_coverage is None or rejected_coverage < 0.80):
        blockers.append("rejected_forward_outcome_coverage_below_80pct")
    if approved_rows and (approved_exit_outcome_rate is None or approved_exit_outcome_rate < 0.80):
        blockers.append("approved_exit_outcome_coverage_below_80pct")
    if candidate["rows"] == 0:
        blockers.append("missing_candidate_universe_rows")
    elif (
        candidate["forward_outcome_coverage_rate"] is None
        or candidate["forward_outcome_coverage_rate"] < 0.80
    ):
        blockers.append("candidate_forward_outcome_coverage_below_80pct")
    if int(pattern_summary.get("pattern_rows") or 0) == 0 and rows:
        blockers.append("missing_symbol_pattern_rows")
    calibration_ready_buckets = int(calibration_summary.get("ready_bucket_count") or 0)
    if calibration_ready_buckets == 0 and rows_with_outcome >= 100:
        blockers.append("no_ready_calibration_buckets")
    if rows_with_outcome and not progress["fully_integrated_outcome_rows"]:
        blockers.append("missing_fully_integrated_pattern_momentum_prediction_outcomes")
    if not learning_effect["strategy_memory_available"]:
        blockers.append("strategy_memory_artifact_missing")
    elif not learning_effect["strategy_memory_trade_count"]:
        blockers.append("strategy_memory_has_no_trade_rows")
    if rows and not learning_effect["decision_policy_rows"]:
        blockers.append("decision_policy_learning_effect_not_recorded")

    not_ready_features = [item for item in guardrails if item.get("status") == "not_ready"]
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
        "clean_for_authority_promotion": (stage == "authority_candidate_review" and not blockers),
        "authority_note": "diagnostic only; this report cannot approve, size, or execute trades",
    }

    next_actions = []
    if "runtime_health_not_clean" in blockers:
        next_actions.append(
            "run runtime-health/runtime-health-trend and clear failed or launcher-error jobs"
        )
    if "missing_runtime_job_runs" in blockers:
        next_actions.append("confirm scheduled jobs are using job_runner.py and writing job_runs")
    if "missing_outcome_rows" in blockers:
        next_actions.append(
            "wait for or backfill realized/forward outcomes before drawing expectancy conclusions"
        )
    if "rejected_forward_outcome_coverage_below_80pct" in blockers:
        next_actions.append(
            "backfill rejected_signal_outcomes before trusting counterfactual analysis"
        )
    if "approved_exit_outcome_coverage_below_80pct" in blockers:
        next_actions.append("classify open positions versus missing approved exit outcomes")
    if (
        approved_rows
        and approved_exit_rate is not None
        and approved_exit_rate < 0.80
        and approved_exit_outcome_rate is not None
        and approved_exit_outcome_rate >= 0.80
    ):
        next_actions.append(
            "repair canonical exit snapshot capture; matched exits are available for learning"
        )
    if "missing_candidate_universe_rows" in blockers:
        next_actions.append("verify candidate-universe capture is running with scope=all")
    if "candidate_forward_outcome_coverage_below_80pct" in blockers:
        next_actions.append(
            "run candidate-outcome-backfill until candidate forward-outcome coverage is at least 80%"
        )
    if "no_ready_calibration_buckets" in blockers:
        next_actions.append("collect more outcomes before using bucket calibration for promotion")
    elif calibration_ready_buckets == 0 and rows_with_outcome:
        next_actions.append(
            "continue baseline collection before using bucket calibration for promotion"
        )
    if "missing_fully_integrated_pattern_momentum_prediction_outcomes" in blockers:
        next_actions.append(
            "verify canonical rows include outcome + pattern + momentum + prediction fields"
        )
    if "strategy_memory_artifact_missing" in blockers:
        next_actions.append("run strategy_learner.py after close so live policy has learned memory")
    if "strategy_memory_has_no_trade_rows" in blockers:
        next_actions.append("rebuild matched trades and regenerate strategy_memory.json")
    if "decision_policy_learning_effect_not_recorded" in blockers:
        next_actions.append("verify decision snapshots include canonical decision_policy_outcome")
    if not next_actions:
        next_actions.append("review feature candidates manually before any authority wiring")

    return LearningReadinessPayload(
        summary=summary,
        lifecycle={
            "rows": int(lifecycle_summary.get("rows") or 0),
            "approved_rows": approved_rows,
            "approved_exit_link_rate": approved_exit_rate,
            "approved_matched_exit_coverage_rate": approved_matched_exit_rate,
            "approved_exit_outcome_coverage_rate": approved_exit_outcome_rate,
            "rejected_trade_backed": rejected_trade_backed,
            "rejected_counterfactual_coverage_rate": rejected_coverage,
            "analysis_ready": bool(lifecycle_summary.get("analysis_ready")),
        },
        runtime_health={
            "job_run_rows": int(runtime.get("rows") or 0),
            "job_count": len(runtime.get("jobs") or []),
            "clean": bool(runtime.get("clean")),
            "failures": sum(int(job.get("failures") or 0) for job in runtime.get("jobs") or []),
            "launcher_errors": sum(
                int(job.get("launcher_errors") or 0) for job in runtime.get("jobs") or []
            ),
            "lock_skips": sum(int(job.get("lock_skips") or 0) for job in runtime.get("jobs") or []),
            "zero_row_successes": sum(
                int(job.get("zero_row_successes") or 0) for job in runtime.get("jobs") or []
            ),
            "rows_written": sum(
                int(job.get("rows_written") or 0) for job in runtime.get("jobs") or []
            ),
        },
        candidate_universe={
            **candidate,
            "candidate_rows_per_lifecycle_row": (
                round(candidate["rows"] / int(lifecycle_summary.get("rows") or 1), 4)
                if lifecycle_summary.get("rows")
                else None
            ),
        },
        learning_effect=learning_effect,
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
        progress=progress,
        blockers=blockers,
        next_actions=next_actions,
    )
