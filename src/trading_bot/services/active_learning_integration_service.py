"""Diagnostic checks for whether learning is actively integrated.

This is not a promotion or authority surface.  It answers a narrower
operational question: are the intelligence layers being read, recorded, and
used by current decision plumbing, or are they only passive artifacts?
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Iterable

from services.intelligence.candidates.outcome_coverage import summarize_candidate_outcome_coverage

ACTIVE_LEARNING_INTEGRATION_VERSION = "active_learning_integration_v1"
RUNTIME_EFFECT = "diagnostic_only_no_live_authority"


@dataclass(frozen=True)
class ActiveLearningIntegrationPayload:
    summary: dict[str, Any]
    auto_buy_path: dict[str, Any]
    lifecycle_path: dict[str, Any]
    strategy_memory: dict[str, Any]
    candidate_universe: dict[str, Any]
    blockers: list[str]
    next_actions: list[str]


def _rate(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(count / total, 4)


def _load_json(raw: Any) -> dict[str, Any]:
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


def _meaningful(value: Any, *, defaults: set[str] | None = None) -> bool:
    if value is None or value == "":
        return False
    text = str(value).strip().lower()
    return text not in (defaults or {"unknown", "none", "not_applicable"})


def _auto_buy_summary(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows_list = [dict(row) for row in rows]
    strategy_memory_rows = 0
    strategy_memory_constrained = 0
    pattern_rows = 0
    pattern_authority_rows = 0
    ml_rows = 0
    setup_rows = 0
    webull_market_rows = 0
    submitted = 0
    broker_failure_detail_rows = 0

    for row in rows_list:
        reason = str(row.get("reason") or "")
        candidate = _load_json(row.get("candidate_json"))
        candidate_payload = (
            candidate.get("candidate")
            if isinstance(candidate.get("candidate"), dict)
            else candidate
        )
        if "strategy_memory:" in reason:
            strategy_memory_rows += 1
        if "strategy_memory_caution" in reason or "strategy_memory_avoid" in str(
            row.get("hard_block_reason") or ""
        ):
            strategy_memory_constrained += 1
        pattern = candidate_payload.get("symbol_pattern") or _path(
            candidate_payload,
            "ai_pattern",
            "pattern_label",
        )
        if _meaningful(
            pattern,
            defaults={"unknown", "mixed_or_unclassified_pattern", "none"},
        ):
            pattern_rows += 1
        runtime_effect = str(
            candidate_payload.get("pattern_runtime_effect")
            or candidate_payload.get("runtime_effect")
            or ""
        )
        if (
            runtime_effect
            and "observe_only" not in runtime_effect
            and "capture_only" not in runtime_effect
        ):
            pattern_authority_rows += 1
        if candidate_payload.get("ml_prediction_score") is not None or _meaningful(
            candidate_payload.get("ml_prediction_bucket"),
            defaults={"unknown", "none"},
        ):
            ml_rows += 1
        if _meaningful(candidate_payload.get("setup_label")) or _meaningful(
            candidate_payload.get("setup_recommendation")
        ):
            setup_rows += 1
        webull_context = candidate_payload.get("webull_market_context")
        webull_tags = candidate_payload.get("webull_market_evidence_tags")
        performance_evidence = candidate_payload.get("performance_evidence")
        has_webull_context = isinstance(webull_context, dict) and bool(webull_context)
        has_webull_tags = isinstance(webull_tags, list) and bool(webull_tags)
        has_webull_performance_evidence = isinstance(performance_evidence, list) and any(
            str(tag).startswith("webull_market:") for tag in performance_evidence
        )
        if has_webull_context or has_webull_tags or has_webull_performance_evidence:
            webull_market_rows += 1
        if row.get("order_submitted"):
            submitted += 1
        if "broker returned no order:" in str(row.get("live_block_reason") or ""):
            broker_failure_detail_rows += 1

    total = len(rows_list)
    return {
        "rows": total,
        "submitted_rows": submitted,
        "strategy_memory_rows": strategy_memory_rows,
        "strategy_memory_row_rate": _rate(strategy_memory_rows, total),
        "strategy_memory_constrained_rows": strategy_memory_constrained,
        "symbol_pattern_rows": pattern_rows,
        "symbol_pattern_row_rate": _rate(pattern_rows, total),
        "symbol_pattern_authority_rows": pattern_authority_rows,
        "ml_prediction_rows": ml_rows,
        "ml_prediction_row_rate": _rate(ml_rows, total),
        "setup_quality_rows": setup_rows,
        "setup_quality_row_rate": _rate(setup_rows, total),
        "webull_market_evidence_rows": webull_market_rows,
        "webull_market_evidence_row_rate": _rate(webull_market_rows, total),
        "broker_failure_detail_rows": broker_failure_detail_rows,
    }


def _lifecycle_summary(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows_list = [dict(row) for row in rows]
    outcomes = 0
    pattern_outcomes = 0
    momentum_outcomes = 0
    prediction_outcomes = 0
    decision_policy_rows = 0
    decision_policy_enforced = 0

    for row in rows_list:
        has_outcome = row.get("realized_return_pct") is not None or any(
            row.get(key) is not None
            for key in (
                "rejected_return_60m",
                "rejected_return_30m",
                "rejected_return_eod",
            )
        )
        canonical = _load_json(row.get("canonical_intelligence_json"))
        pattern = row.get("symbol_pattern") or _path(canonical, "pattern_state", "pattern_label")
        momentum = row.get("session_trend_label") or _path(
            canonical, "momentum_state", "session_label"
        )
        prediction = row.get("prediction_score") or _path(canonical, "prediction_state", "ml_score")
        policy = _path(canonical, "advisory_authority_state", "decision_policy_outcome")
        if isinstance(policy, dict) and policy.get("advisory_decision"):
            decision_policy_rows += 1
            if policy.get("enforced"):
                decision_policy_enforced += 1
        if not has_outcome:
            continue
        outcomes += 1
        if _meaningful(pattern, defaults={"unknown", "mixed_or_unclassified_pattern"}):
            pattern_outcomes += 1
        if _meaningful(momentum):
            momentum_outcomes += 1
        if _meaningful(prediction):
            prediction_outcomes += 1

    return {
        "rows": len(rows_list),
        "rows_with_outcome": outcomes,
        "pattern_outcome_rows": pattern_outcomes,
        "momentum_outcome_rows": momentum_outcomes,
        "prediction_outcome_rows": prediction_outcomes,
        "fully_integrated_outcome_rows": min(
            pattern_outcomes,
            momentum_outcomes,
            prediction_outcomes,
        ),
        "decision_policy_rows": decision_policy_rows,
        "decision_policy_enforced_rows": decision_policy_enforced,
    }


def _candidate_summary(rows: Iterable[dict[str, Any]]) -> dict[str, Any]:
    rows_list = [dict(row) for row in rows]
    coverage = summarize_candidate_outcome_coverage(rows_list)
    return {
        "rows": len(rows_list),
        "rows_with_forward_outcome": coverage["rows_with_forward_outcome"],
        "forward_outcome_rate": coverage["forward_outcome_coverage_rate"],
        "missing_forward_outcome": coverage["missing_forward_outcome"],
        "non_taken_rows": coverage["non_taken_rows"],
        "non_taken_with_forward_outcome": coverage["non_taken_with_forward_outcome"],
        "non_taken_forward_outcome_rate": coverage["non_taken_forward_outcome_coverage_rate"],
        "taken_rows": sum(1 for row in rows_list if row.get("candidate_status") == "taken"),
        "near_threshold_rows": sum(
            1 for row in rows_list if row.get("candidate_status") == "near_threshold"
        ),
        "scored_not_taken_rows": sum(
            1 for row in rows_list if row.get("candidate_status") == "scored_not_taken"
        ),
    }


def _strategy_memory_summary(memory: dict[str, Any] | None) -> dict[str, Any]:
    data = memory if isinstance(memory, dict) else {}
    sections = [
        key
        for key in (
            "setup_label_context",
            "prediction_decision_context",
            "buy_opportunity_context",
            "session_trend_context",
            "symbol_setup_label_context",
            "symbol_prediction_context",
            "symbol_buy_opportunity_context",
            "symbol_session_trend_context",
            "symbol_bar_pattern_label_context",
            "symbol_bar_pattern_opportunity_context",
        )
        if data.get(key)
    ]
    return {
        "available": bool(data),
        "generated_at": data.get("generated_at"),
        "trade_count": int(data.get("trade_count") or 0),
        "nonempty_context_sections": len(sections),
        "sections": sections,
    }


def build_active_learning_integration_payload(
    *,
    lifecycle_rows: Iterable[dict[str, Any]],
    auto_buy_rows: Iterable[dict[str, Any]],
    candidate_rows: Iterable[dict[str, Any]],
    strategy_memory: dict[str, Any] | None = None,
    start_date: str,
    end_date: str,
) -> ActiveLearningIntegrationPayload:
    auto_buy = _auto_buy_summary(auto_buy_rows)
    lifecycle = _lifecycle_summary(lifecycle_rows)
    candidates = _candidate_summary(candidate_rows)
    memory = _strategy_memory_summary(strategy_memory)

    blockers: list[str] = []
    if auto_buy["rows"] == 0:
        blockers.append("no_auto_buy_audit_rows")
    if auto_buy["strategy_memory_rows"] == 0:
        blockers.append("strategy_memory_not_observed_in_auto_buy_path")
    if auto_buy["symbol_pattern_rows"] == 0:
        blockers.append("symbol_pattern_not_observed_in_auto_buy_path")
    if auto_buy["ml_prediction_rows"] == 0:
        blockers.append("ml_prediction_not_observed_in_auto_buy_path")
    if not memory["available"]:
        blockers.append("strategy_memory_artifact_missing")
    elif memory["trade_count"] == 0:
        blockers.append("strategy_memory_has_no_trade_rows")
    if lifecycle["rows_with_outcome"] == 0:
        blockers.append("no_lifecycle_outcomes_for_learning")
    if candidates["rows"] == 0:
        blockers.append("candidate_universe_missing")
    elif candidates["rows_with_forward_outcome"] == 0:
        blockers.append("candidate_forward_outcomes_missing")
    if auto_buy["symbol_pattern_authority_rows"] > 0:
        blockers.append("unexpected_symbol_pattern_authority_leak")

    active_signals = 0
    active_signals += 1 if auto_buy["strategy_memory_rows"] else 0
    active_signals += 1 if auto_buy["symbol_pattern_rows"] else 0
    active_signals += 1 if auto_buy["ml_prediction_rows"] else 0
    active_signals += 1 if auto_buy["webull_market_evidence_rows"] else 0
    active_signals += 1 if auto_buy["strategy_memory_constrained_rows"] else 0
    active_signals += 1 if lifecycle["rows_with_outcome"] else 0
    active_signals += 1 if candidates["rows_with_forward_outcome"] else 0

    summary = {
        "report_version": ACTIVE_LEARNING_INTEGRATION_VERSION,
        "runtime_effect": RUNTIME_EFFECT,
        "start_date": start_date,
        "end_date": end_date,
        "active_learning_signal_count": active_signals,
        "actively_learning": active_signals >= 4
        and "unexpected_symbol_pattern_authority_leak" not in blockers,
        "authority_note": "diagnostic only; this report cannot approve, block, size, or execute trades",
    }

    next_actions = []
    if "strategy_memory_not_observed_in_auto_buy_path" in blockers:
        next_actions.append(
            "verify auto_buy_manager calls memory_for_signal and records strategy_memory reasons"
        )
    if "symbol_pattern_not_observed_in_auto_buy_path" in blockers:
        next_actions.append(
            "verify candidate payloads include symbol_pattern from pattern intelligence"
        )
    if "ml_prediction_not_observed_in_auto_buy_path" in blockers:
        next_actions.append(
            "verify auto_buy_prediction_context is populated during candidate scoring"
        )
    if "no_lifecycle_outcomes_for_learning" in blockers:
        next_actions.append(
            "run trade matching / exit snapshot backfill so approved trades have outcomes"
        )
    if "candidate_forward_outcomes_missing" in blockers:
        next_actions.append("run candidate-outcome-backfill for missed-buy learning")
    if "strategy_memory_artifact_missing" in blockers:
        next_actions.append("run after-close strategy learning to regenerate strategy_memory.json")
    if "unexpected_symbol_pattern_authority_leak" in blockers:
        next_actions.append("remove direct symbol-pattern authority before continuing")
    if not next_actions:
        next_actions.append(
            "review decision-quality and feature-attribution reports before tuning authority"
        )

    return ActiveLearningIntegrationPayload(
        summary=summary,
        auto_buy_path=auto_buy,
        lifecycle_path=lifecycle,
        strategy_memory=memory,
        candidate_universe=candidates,
        blockers=blockers,
        next_actions=next_actions,
    )
