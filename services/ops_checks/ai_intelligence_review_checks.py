"""Operator review for observe-only AI intelligence integrations."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from repositories.candidate_universe_repo import CandidateUniverseRepository
from repositories.job_runs_repo import JobRunsRepository
from repositories.lifecycle_analysis_repo import LifecycleAnalysisRepository
from repositories.ops_check_repo import OpsCheckRepository
from services.ai_review_suite_service import (
    AI_REVIEW_RUNTIME_EFFECT,
    AI_REVIEW_SUITE_VERSION,
    build_ai_review_suite,
)
from services.job_runs_service import JobRunsService
from services.lifecycle_analysis_service import LifecycleAnalysisService
from services.feature_attribution_service import build_feature_attribution_payload
from services.rollout_contract_service import assess_all_feature_family_rollouts


AI_INTELLIGENCE_REVIEW_REPORT_VERSION = "ai_intelligence_review_v1"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _load_json(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        loaded = json.loads(str(raw))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _first_present(rows: list[dict[str, Any]], *keys: str) -> dict[str, Any]:
    for row in rows:
        for key in keys:
            if row.get(key) not in (None, ""):
                return row
    return rows[0] if rows else {}


def _canonical_from_lifecycle(row: dict[str, Any]) -> dict[str, Any]:
    return _load_json(row.get("canonical_intelligence_json"))


def _event_payload(row: dict[str, Any]) -> dict[str, Any]:
    raw = _load_json(row.get("raw_json"))
    return {
        **raw,
        "source": row.get("source") or raw.get("source"),
        "source_url": row.get("source_url") or raw.get("source_url"),
        "event_type": row.get("event_type") or raw.get("event_type"),
        "event_summary": row.get("event_summary") or raw.get("event_summary"),
        "expected_market_impact": (
            row.get("expected_market_impact")
            or raw.get("expected_market_impact")
            or row.get("trade_relevance")
        ),
    }


def _candidate_payload(row: dict[str, Any]) -> dict[str, Any]:
    payload = _load_json(row.get("candidate_json"))
    return {
        **payload,
        "near_threshold": row.get("candidate_status") == "near_threshold",
        "decision": row.get("decision") or row.get("candidate_status"),
        "mfe_pct": payload.get("forward_mfe_pct") or payload.get("max_favorable_60m"),
        "score": row.get("score"),
        "candidate_status": row.get("candidate_status"),
    }


def _feature_families_from_lifecycle(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    families: list[dict[str, Any]] = []
    for row in rows:
        families.extend(
            [
                {
                    "feature_family": "market_regime",
                    "bucket": row.get("market_regime"),
                },
                {
                    "feature_family": "execution_quality",
                    "bucket": row.get("execution_quality_decision")
                    or row.get("execution_cost_bucket"),
                },
                {
                    "feature_family": "portfolio_decision",
                    "bucket": row.get("portfolio_decision"),
                },
                {
                    "feature_family": "market_participation",
                    "bucket": row.get("participation_state"),
                },
                {
                    "feature_family": "volatility_normalization",
                    "bucket": row.get("volatility_chase_risk"),
                },
                {
                    "feature_family": "setup_structure",
                    "bucket": row.get("setup_label"),
                },
                {
                    "feature_family": "downside_asymmetry",
                    "bucket": row.get("downside_state"),
                },
                {
                    "feature_family": "utility_estimate",
                    "bucket": row.get("utility_decision"),
                },
            ]
        )
    return [
        item
        for item in families
        if item.get("bucket") not in (None, "", "unknown")
    ]


def _runtime_health_input(target_date: str, db_path: Path) -> dict[str, Any]:
    try:
        payload = JobRunsService(JobRunsRepository(db_path)).health_payload(
            target_date=target_date,
            limit=100,
        )
        return {
            "ok": bool(payload.summary.get("clean")),
            "rows": payload.summary.get("total_runs"),
            "warnings": (
                ["runtime_health_not_clean"]
                if not payload.summary.get("clean")
                else []
            ),
            "missing_count": 0 if payload.rows else 1,
        }
    except Exception:
        return {
            "ok": False,
            "warnings": ["runtime_health_unavailable"],
            "missing_count": 1,
        }


def _rollout_assessment(rows: list[dict[str, Any]], target_date: str) -> dict[str, Any]:
    attribution = build_feature_attribution_payload(rows, min_sample_size=1)
    if not attribution.summary.get("rows_with_outcome"):
        return {
            "status": "not_ready",
            "failed_thresholds": ["no_lifecycle_rows_with_outcomes"],
        }
    payload = assess_all_feature_family_rollouts(
        attribution_payload=attribution,
        decision_date=target_date,
        review_window_start=target_date,
        review_window_end=target_date,
    )
    status_counts: dict[str, int] = {}
    failures: list[str] = []
    for assessment in payload.assessments:
        status_counts[assessment.status.value] = (
            status_counts.get(assessment.status.value, 0) + 1
        )
        failures.extend(assessment.guardrail_failures[:2])
    return {
        "status": (
            "size_down_candidate"
            if status_counts.get("size_down_candidate")
            else "narrow_block_candidate"
            if status_counts.get("narrow_block_candidate")
            else "observe_only"
            if status_counts.get("observe_only")
            else "not_ready"
        ),
        "failed_thresholds": sorted(set(failures))[:8],
        "status_counts": status_counts,
    }


def run_ai_intelligence_review(
    target_date: str,
    *,
    base_dir: Path,
    symbol: str | None = None,
    samples: int = 10,
) -> bool:
    print()
    print("=" * 72)
    print(f"  AI Intelligence Integration Review - {target_date}")
    print("=" * 72)
    print(f"report_version          : {AI_INTELLIGENCE_REVIEW_REPORT_VERSION}")
    print(f"ai_review_version       : {AI_REVIEW_SUITE_VERSION}")
    print(f"runtime_effect          : {AI_REVIEW_RUNTIME_EFFECT}")
    print("authority               : review_only_no_trade_authority")

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    lifecycle = LifecycleAnalysisService(LifecycleAnalysisRepository(db_path))
    lifecycle_payload = lifecycle.payload(start_date=target_date, symbol=symbol)
    lifecycle_rows = lifecycle_payload.rows

    candidate_rows = [
        dict(row)
        for row in CandidateUniverseRepository(db_path).rows_for_date(
            target_date,
            symbol=symbol,
        )
    ]
    event_rows = [
        dict(row)
        for row in OpsCheckRepository(db_path).event_source_rows(target_date)
    ]

    focus_lifecycle = _first_present(
        lifecycle_rows,
        "canonical_intelligence_json",
        "rejected_outcome_id",
        "exit_snapshot_id",
    )
    canonical = _canonical_from_lifecycle(focus_lifecycle)
    event = _event_payload(event_rows[0]) if event_rows else {}
    candidates = [_candidate_payload(row) for row in candidate_rows]
    ops_inputs = {
        "runtime_health": _runtime_health_input(target_date, db_path),
        "lifecycle_analysis": {
            "ok": bool(lifecycle_payload.summary.get("analysis_ready")),
            "missing_count": lifecycle_payload.summary.get(
                "rejected_without_counterfactual",
                0,
            ),
        },
        "event_validation": {
            "ok": bool(event_rows),
            "missing_count": 0 if event_rows else 1,
        },
    }
    feature_families = _feature_families_from_lifecycle(lifecycle_rows)
    rollout = _rollout_assessment(lifecycle_rows, target_date)
    suite = build_ai_review_suite(
        symbol=symbol,
        canonical=canonical,
        lifecycle_row=focus_lifecycle,
        candidates=candidates,
        event=event,
        ops_inputs=ops_inputs,
        feature_families=feature_families,
        rollout_assessment=rollout,
    )

    print()
    print("Input coverage")
    print(f"  lifecycle_rows        : {len(lifecycle_rows)}")
    print(f"  candidate_rows        : {len(candidate_rows)}")
    print(f"  event_rows            : {len(event_rows)}")
    print(f"  feature_family_rows   : {len(feature_families)}")
    print(f"  lifecycle_ready       : {lifecycle_payload.summary.get('analysis_ready')}")

    sections = [
        ("1. Context interpreter", "source_evidence_audit", "audit_result"),
        ("2. Pattern summarizer", "setup_structure", "review_label"),
        ("3. Disagreement reviewer", "policy_disagreement", "summary"),
        ("4. Post-trade analyst", "lifecycle_trade_review", "review_label"),
        ("5. Governance assistant", "model_readiness", "review_label"),
        ("6. Source reliability auditor", "source_evidence_audit", "issue"),
        ("7. Candidate-universe reviewer", "candidate_universe_review", "review_label"),
        ("8. Explicit AI contract", "policy_disagreement", "authority"),
        ("9. Promotion path reviewer", "model_readiness", "status"),
        ("10. Practical integration tasks", "remediation_tasks", "review_label"),
    ]
    print()
    print("Recommendation coverage")
    for title, section, field in sections:
        payload = _dict(suite.get(section))
        value = payload.get(field)
        if value in (None, "") and field == "issue":
            value = "no_issue"
        print(f"  {title:<34} {value}")

    print()
    print("Detailed review labels")
    print(
        "  policy_conflict       : "
        f"{suite['policy_disagreement']['conflict_detected']}"
    )
    print(
        "  negative_sources      : "
        f"{suite['policy_disagreement']['negative_sources']}"
    )
    print(
        "  candidate_count       : "
        f"{suite['candidate_universe_review']['candidate_count']}"
    )
    print(
        "  near_threshold        : "
        f"{suite['candidate_universe_review']['near_threshold_count']}"
    )
    print(
        "  source_audit          : "
        f"{suite['source_evidence_audit']['audit_result']}"
    )
    print(
        "  operator_briefing     : "
        f"{suite['daily_operator_briefing']['briefing_label']}"
    )
    print(
        "  exit_pattern          : "
        f"{suite['exit_pattern']['review_label']}"
    )
    print(
        "  overlap_risk          : "
        f"{suite['feature_overlap']['overlap_risk']}"
    )
    print(
        "  readiness_status      : "
        f"{suite['model_readiness']['status']}"
    )
    print(
        "  remediation_tasks     : "
        f"{suite['remediation_tasks']['tasks'][:samples]}"
    )

    ok = bool(lifecycle_rows or candidate_rows or event_rows)
    print()
    print(
        "[OK] AI intelligence review completed; no live authority changed"
        if ok
        else "[WARN] no intelligence evidence rows found"
    )
    return ok
