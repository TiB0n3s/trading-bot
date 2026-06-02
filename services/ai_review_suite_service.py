"""Observe-only AI-style review helpers for trading intelligence.

These helpers convert already-built telemetry into compact review payloads.
They do not fetch data, call a model, approve/reject signals, size orders, or
change execution. The outputs are intended for reports, replay, and operator
review.
"""

from __future__ import annotations

from collections import Counter
from typing import Any


AI_REVIEW_SUITE_VERSION = "ai_review_suite_v1"
AI_REVIEW_RUNTIME_EFFECT = "observe_only_no_live_authority"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _str(value: Any, default: str = "unknown") -> str:
    text = str(value if value is not None else default).strip()
    return text or default


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _base(kind: str) -> dict[str, Any]:
    return {
        "version": AI_REVIEW_SUITE_VERSION,
        "kind": kind,
        "runtime_effect": AI_REVIEW_RUNTIME_EFFECT,
        "authority": "review_only_no_trade_authority",
    }


def policy_disagreement_explainer(
    *,
    advisory_authority_state: dict[str, Any] | None = None,
    approved: bool | None = None,
) -> dict[str, Any]:
    state = _dict(advisory_authority_state)
    checks = {
        "decision_policy": _dict(state.get("decision_policy_outcome")).get("advisory_decision"),
        "ml": _dict(state.get("ml_outcome")).get("advisory_decision"),
        "session_gate": _dict(state.get("session_gate_outcome")).get("advisory_decision"),
        "setup_quality": _dict(state.get("setup_quality_outcome")).get("advisory_decision"),
        "portfolio": _dict(state.get("portfolio_decision")).get("decision"),
        "execution_quality": _dict(state.get("execution_quality")).get("decision"),
    }
    negative = {
        name: decision
        for name, decision in checks.items()
        if _str(decision, "") in {"block", "avoid", "caution", "size_down", "reduce"}
    }
    positive = {
        name: decision
        for name, decision in checks.items()
        if _str(decision, "") in {"allow", "buy", "favorable", "approve"}
    }
    conflict = bool(negative and positive) or (approved is True and bool(negative))
    out = _base("policy_disagreement")
    out.update(
        {
            "conflict_detected": conflict,
            "negative_sources": sorted(negative),
            "positive_sources": sorted(positive),
            "summary": (
                "mixed advisory signals"
                if conflict
                else "advisory signals broadly aligned or insufficient"
            ),
        }
    )
    return out


def lifecycle_trade_reviewer(row: dict[str, Any] | None = None) -> dict[str, Any]:
    row = _dict(row)
    approved = bool(row.get("approved"))
    status = _str(row.get("lifecycle_status"))
    realized = _float(row.get("realized_return_pct"))
    rejected_mfe = _float(row.get("rejected_max_favorable_60m"))
    missed = rejected_mfe is not None and rejected_mfe > 0.5 and not approved
    out = _base("lifecycle_trade_review")
    out.update(
        {
            "status": status,
            "approved": approved,
            "review_label": (
                "approved_profitable" if approved and realized is not None and realized > 0
                else "approved_loss_or_flat" if approved
                else "rejected_missed_opportunity" if missed
                else "rejected_contained_or_unknown"
            ),
            "focus": (
                "exit_quality" if approved else "counterfactual_outcome_coverage"
            ),
        }
    )
    return out


def candidate_universe_reviewer(rows: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    rows = rows or []
    total = len(rows)
    near_threshold = sum(1 for r in rows if bool(r.get("near_threshold")))
    skipped = sum(1 for r in rows if _str(r.get("decision")) in {"skip", "rejected"})
    good = sum(1 for r in rows if (_float(r.get("mfe_pct")) or 0) > 1.0)
    out = _base("candidate_universe_review")
    out.update(
        {
            "candidate_count": total,
            "near_threshold_count": near_threshold,
            "skipped_count": skipped,
            "later_good_count": good,
            "review_label": "needs_candidate_coverage" if total == 0 else "candidate_coverage_available",
        }
    )
    return out


def source_evidence_auditor(event: dict[str, Any] | None = None) -> dict[str, Any]:
    event = _dict(event)
    tier = _str(event.get("source_tier"))
    impact = _str(event.get("expected_market_impact"), "").lower()
    confirmation = _str(event.get("confirmation_status"))
    bullish = "bullish" in impact or "positive" in impact
    issue = None
    if bullish and tier not in {"official", "confirmed_financial_news", "deep_analysis"}:
        issue = "directional_inference_lacks_trusted_source"
    elif confirmation in {"unconfirmed", "needs_confirmation"}:
        issue = "needs_confirmation"
    out = _base("source_evidence_audit")
    out.update(
        {
            "source_tier": tier,
            "confirmation_status": confirmation,
            "audit_result": "needs_review" if issue else "supported_or_neutral",
            "issue": issue,
        }
    )
    return out


def daily_operator_briefing(inputs: dict[str, Any] | None = None) -> dict[str, Any]:
    inputs = _dict(inputs)
    warnings = []
    for key in ("runtime_health", "context_freshness", "setup_breakdown", "event_validation"):
        section = _dict(inputs.get(key))
        if section.get("ok") is False or section.get("warnings"):
            warnings.append(key)
    out = _base("daily_operator_briefing")
    out.update(
        {
            "warning_sections": warnings,
            "briefing_label": "attention_required" if warnings else "no_major_warnings",
            "recommended_next_step": warnings[0] if warnings else "standard_review",
        }
    )
    return out


def exit_pattern_interpreter(exit_state: dict[str, Any] | None = None) -> dict[str, Any]:
    state = _dict(exit_state)
    pressure = _str(state.get("exit_pressure_state") or state.get("exit_trigger"))
    missed_upside = _float(state.get("missed_upside_pct"))
    avoided = _float(state.get("avoided_drawdown_pct"))
    out = _base("exit_pattern")
    out.update(
        {
            "exit_pressure_state": pressure,
            "review_label": (
                "potentially_early_exit" if missed_upside is not None and missed_upside > 1.0
                else "drawdown_protection" if avoided is not None and avoided > 0.5
                else "exit_needs_more_outcome_data"
            ),
        }
    )
    return out


def feature_overlap_detector(feature_families: list[dict[str, Any]] | None = None) -> dict[str, Any]:
    families = feature_families or []
    token_counts: Counter[str] = Counter()
    for family in families:
        for key in ("family", "feature_family", "primary_signal", "bucket"):
            value = family.get(key)
            if value:
                for token in str(value).replace("_", " ").split():
                    token_counts[token.lower()] += 1
    overlap_tokens = sorted(token for token, count in token_counts.items() if count > 1)
    out = _base("feature_overlap")
    out.update(
        {
            "family_count": len(families),
            "overlap_tokens": overlap_tokens[:10],
            "overlap_risk": "elevated" if overlap_tokens else "low",
        }
    )
    return out


def model_readiness_reviewer(assessment: dict[str, Any] | None = None) -> dict[str, Any]:
    assessment = _dict(assessment)
    status = _str(assessment.get("status"), "not_ready")
    failures = assessment.get("failed_thresholds") or assessment.get("failures") or []
    out = _base("model_readiness")
    out.update(
        {
            "status": status,
            "failed_thresholds": [str(item) for item in failures],
            "review_label": "promotion_candidate" if status in {"size_down_candidate", "narrow_block_candidate"} else "not_ready_or_observe",
        }
    )
    return out


def setup_structure_explainer(setup_state: dict[str, Any] | None = None) -> dict[str, Any]:
    setup = _dict(setup_state)
    quality = _str(setup.get("quality_recommendation") or setup.get("recommendation"))
    structure = _str(setup.get("structure_state"))
    failed = _str(setup.get("failed_breakout_risk"))
    out = _base("setup_structure")
    out.update(
        {
            "quality": quality,
            "structure_state": structure,
            "failed_breakout_risk": failed,
            "review_label": (
                "clean_setup" if quality in {"favorable", "premium"} and failed in {"low", "unknown"}
                else "messy_or_unconfirmed_setup"
            ),
        }
    )
    return out


def remediation_task_generator(checks: dict[str, Any] | None = None) -> dict[str, Any]:
    checks = _dict(checks)
    tasks = []
    for name, payload in checks.items():
        payload = _dict(payload)
        if payload.get("ok") is False:
            tasks.append(f"review_{name}")
        if payload.get("missing_count"):
            tasks.append(f"backfill_{name}")
        if payload.get("stale_count"):
            tasks.append(f"refresh_{name}")
    out = _base("remediation_tasks")
    out.update(
        {
            "tasks": tasks[:10],
            "task_count": len(tasks),
            "review_label": "no_tasks" if not tasks else "action_items_available",
        }
    )
    return out


def build_ai_review_suite(
    *,
    symbol: str | None = None,
    canonical: dict[str, Any] | None = None,
    lifecycle_row: dict[str, Any] | None = None,
    candidates: list[dict[str, Any]] | None = None,
    event: dict[str, Any] | None = None,
    ops_inputs: dict[str, Any] | None = None,
    feature_families: list[dict[str, Any]] | None = None,
    rollout_assessment: dict[str, Any] | None = None,
) -> dict[str, Any]:
    canonical = _dict(canonical)
    return {
        "version": AI_REVIEW_SUITE_VERSION,
        "runtime_effect": AI_REVIEW_RUNTIME_EFFECT,
        "symbol": symbol,
        "policy_disagreement": policy_disagreement_explainer(
            advisory_authority_state=canonical.get("advisory_authority_state"),
            approved=(lifecycle_row or {}).get("approved") if lifecycle_row else None,
        ),
        "lifecycle_trade_review": lifecycle_trade_reviewer(lifecycle_row),
        "candidate_universe_review": candidate_universe_reviewer(candidates),
        "source_evidence_audit": source_evidence_auditor(event),
        "daily_operator_briefing": daily_operator_briefing(ops_inputs),
        "exit_pattern": exit_pattern_interpreter(
            (canonical.get("regime_state") or {})
            | (canonical.get("exit_state") or {})
        ),
        "feature_overlap": feature_overlap_detector(feature_families),
        "model_readiness": model_readiness_reviewer(rollout_assessment),
        "setup_structure": setup_structure_explainer(canonical.get("setup_state")),
        "remediation_tasks": remediation_task_generator(ops_inputs),
    }

