"""Advisory-vs-authority decision audit."""

from __future__ import annotations

import json
from collections import Counter
from pathlib import Path
from typing import Any

from repositories.ops_check_repo import OpsCheckRepository

ADVISORY_AUTHORITY_REPORT_VERSION = "advisory_authority_v1"


def _load_json(raw: str | None) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        loaded = json.loads(raw)
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def _is_approved(row: dict[str, Any]) -> bool:
    return bool(row.get("approved"))


def _increment_if(counter: Counter, key: str, condition: bool) -> None:
    if condition:
        counter[key] += 1


def _canonical_authority_state(row: dict[str, Any]) -> dict[str, Any]:
    canonical = _load_json(row.get("canonical_intelligence_json"))
    state = canonical.get("advisory_authority_state") if canonical else None
    return state if isinstance(state, dict) else {}


def _outcome(
    authority_state: dict[str, Any],
    key: str,
    fallback: dict[str, Any],
) -> dict[str, Any]:
    normalized = authority_state.get(key)
    if isinstance(normalized, dict) and normalized:
        return normalized
    return fallback


def _legacy_decision_policy_outcome(account_state: dict[str, Any]) -> dict[str, Any]:
    # Compatibility only: new reports should consume decision_policy_outcome.
    authority = account_state.get("decision_policy_authority") or {}
    decision_policy = account_state.get("decision_policy") or {}
    decision = decision_policy.get("decision")
    size_down_applied = bool(account_state.get("decision_policy_size_down"))
    return {
        "advisory_decision": decision,
        "authority_mode": authority.get("authority_mode") or "unknown",
        "enforced": bool(size_down_applied),
        "effect_on_size": "size_down" if size_down_applied else "none",
        "effect_on_execution": "none",
        "reason": decision_policy.get("reason"),
    }


def _legacy_ml_outcome(account_state: dict[str, Any]) -> dict[str, Any]:
    # Compatibility only: new reports should consume ml_outcome.
    prediction_gate = account_state.get("prediction_gate") or {}
    ml_authority = account_state.get("ml_authority") or prediction_gate.get("ml_authority") or {}
    mode = ml_authority.get("authority_mode", ml_authority.get("mode")) or "unknown"
    advisory_decision = prediction_gate.get("ml_prediction_compare_decision")
    if ml_authority.get("advisory_decision") is not None:
        advisory_decision = ml_authority.get("advisory_decision")
    return {
        "advisory_decision": advisory_decision,
        "authority_mode": mode,
        "qualified_for_authority": bool(ml_authority.get("qualified_for_authority")),
        "enforced": bool(ml_authority.get("enforced")),
        "effect_on_size": ml_authority.get("effect_on_size") or "none",
        "effect_on_execution": ml_authority.get("effect_on_execution") or "none",
        "would_block_under_promoted_mode": bool(
            ml_authority.get("would_block_under_promoted_mode")
        ),
        "safety_check_passed": ml_authority.get("safety_check_passed", True),
        "reason": ml_authority.get("reason"),
    }


def _legacy_session_gate_outcome(account_state: dict[str, Any]) -> dict[str, Any]:
    # Compatibility only: new reports should consume session_gate_outcome.
    session_gate = account_state.get("session_momentum_gate") or {}
    would_block = bool(session_gate.get("would_block"))
    return {
        "advisory_decision": "block" if would_block else session_gate.get("severity"),
        "authority_mode": "legacy_unknown",
        "enforced": False,
        "effect_on_size": "cap"
        if session_gate.get("severity") in ("soft_negative", "reversal_caution", "hard_negative")
        else "none",
        "effect_on_execution": "none",
        "reason": session_gate.get("reason"),
    }


def _legacy_setup_quality_outcome(account_state: dict[str, Any]) -> dict[str, Any]:
    # Compatibility only: new reports should consume setup_quality_outcome.
    setup_quality = account_state.get("setup_quality") or {}
    return {
        "advisory_decision": setup_quality.get("recommendation"),
        "authority_mode": "legacy_context",
        "enforced": False,
        "effect_on_size": "none",
        "effect_on_execution": "none",
        "label": setup_quality.get("label"),
        "score": setup_quality.get("score"),
        "confidence": setup_quality.get("confidence"),
        "source": setup_quality.get("source"),
        "fallback": setup_quality.get("fallback"),
    }


def _canonical_nested_outcome(
    authority_state: dict[str, Any],
    key: str,
) -> dict[str, Any]:
    value = authority_state.get(key)
    return value if isinstance(value, dict) else {}


def run_advisory_authority_report(target_date: str, *, base_dir: Path) -> bool:
    print()
    print("=" * 72)
    print(f"  Advisory vs Authority Report - {target_date}")
    print("=" * 72)
    print(f"report_version          : {ADVISORY_AUTHORITY_REPORT_VERSION}")

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    repo = OpsCheckRepository(db_path)
    rows = [dict(row) for row in repo.decision_authority_rows(target_date)]
    if not rows:
        print("[WARN] no decision snapshot rows found")
        return False

    counts = Counter()
    mode_counts = Counter()
    ml_mode_counts = Counter()
    examples: list[dict[str, Any]] = []

    for row in rows:
        account_state = _load_json(row.get("account_state_json"))
        authority_state = _canonical_authority_state(row)
        approved = _is_approved(row)
        action = (row.get("action") or "").lower()
        counts["rows"] += 1
        _increment_if(counts, "buy_rows", action == "buy")
        _increment_if(counts, "approved_rows", approved)

        decision_policy_outcome = _outcome(
            authority_state,
            "decision_policy_outcome",
            _legacy_decision_policy_outcome(account_state),
        )
        mode = decision_policy_outcome.get("authority_mode") or "unknown"
        mode_counts[mode] += 1

        dp_decision = decision_policy_outcome.get("advisory_decision")
        dp_block = action == "buy" and dp_decision == "block"
        dp_size_down = action == "buy" and dp_decision == "size_down"
        dp_size_down_applied = bool(
            decision_policy_outcome.get("enforced")
            and decision_policy_outcome.get("effect_on_size") in ("size_down", "cap")
        )

        ml_outcome = _outcome(
            authority_state,
            "ml_outcome",
            _legacy_ml_outcome(account_state),
        )
        ml_compare = ml_outcome.get("advisory_decision")
        ml_authority_mode = ml_outcome.get("authority_mode") or "unknown"
        if action == "buy":
            ml_mode_counts[ml_authority_mode] += 1
        ml_negative = action == "buy" and ml_compare in ("avoid", "block", "caution")
        ml_ignored_by_design = (
            ml_negative
            and ml_authority_mode == "observe_only_compare"
            and not ml_outcome.get("enforced")
        )
        ml_would_block_under_promoted_mode = action == "buy" and bool(
            ml_outcome.get("would_block_under_promoted_mode")
        )
        ml_qualified = action == "buy" and bool(ml_outcome.get("qualified_for_authority"))
        ml_enforced = action == "buy" and bool(ml_outcome.get("enforced"))
        ml_size_down = ml_enforced and ml_outcome.get("effect_on_size") == "cap"
        ml_block_enforced = ml_enforced and ml_outcome.get("effect_on_execution") == "block"
        ml_not_enforced_due_to_mode = (
            ml_qualified
            and not ml_enforced
            and ml_authority_mode in ("observe_only_compare", "paper_block")
        )
        ml_live_block_refused = (
            ml_qualified
            and not ml_enforced
            and ml_authority_mode == "live_block"
            and not ml_outcome.get("safety_check_passed", True)
        )

        session_outcome = _outcome(
            authority_state,
            "session_gate_outcome",
            _legacy_session_gate_outcome(account_state),
        )
        session_would_block = (
            action == "buy" and session_outcome.get("advisory_decision") == "block"
        )

        setup_outcome = _outcome(
            authority_state,
            "setup_quality_outcome",
            _legacy_setup_quality_outcome(account_state),
        )
        setup_score = setup_outcome.get("score")
        setup_recommendation = setup_outcome.get("advisory_decision")
        weak_setup = action == "buy" and (
            setup_recommendation == "avoid"
            or (isinstance(setup_score, (int, float)) and setup_score < 40)
        )

        portfolio_outcome = _canonical_nested_outcome(authority_state, "portfolio_decision")
        portfolio_decision = portfolio_outcome.get("decision")
        portfolio_negative = action == "buy" and portfolio_decision in ("block", "size_down")
        portfolio_block = action == "buy" and portfolio_decision == "block"
        portfolio_size_down = action == "buy" and portfolio_decision == "size_down"

        execution_outcome = _canonical_nested_outcome(authority_state, "execution_quality")
        execution_decision = execution_outcome.get("decision")
        execution_negative = action == "buy" and execution_decision in (
            "avoid",
            "block",
            "size_down",
        )
        execution_block = action == "buy" and execution_decision in ("avoid", "block")
        execution_size_down = action == "buy" and execution_decision == "size_down"

        _increment_if(counts, "decision_policy_block_advisory", dp_block)
        _increment_if(counts, "decision_policy_block_but_approved", dp_block and approved)
        _increment_if(counts, "decision_policy_size_down_advisory", dp_size_down)
        _increment_if(
            counts,
            "decision_policy_size_down_not_applied",
            dp_size_down and not dp_size_down_applied,
        )
        _increment_if(counts, "ml_negative_compare_advisory", ml_negative)
        _increment_if(counts, "ml_negative_compare_but_approved", ml_negative and approved)
        _increment_if(counts, "ml_negative_compare_ignored_by_design", ml_ignored_by_design)
        _increment_if(
            counts,
            "ml_negative_compare_would_block_under_promoted_mode",
            ml_would_block_under_promoted_mode,
        )
        _increment_if(counts, "ml_authority_qualified", ml_qualified)
        _increment_if(counts, "ml_authority_not_enforced_due_to_mode", ml_not_enforced_due_to_mode)
        _increment_if(counts, "ml_authority_live_block_refused", ml_live_block_refused)
        _increment_if(counts, "ml_authority_triggered", ml_enforced)
        _increment_if(counts, "ml_authority_size_down", ml_size_down)
        _increment_if(counts, "ml_authority_block_enforced", ml_block_enforced)
        _increment_if(counts, "session_would_block_advisory", session_would_block)
        _increment_if(counts, "session_would_block_but_approved", session_would_block and approved)
        _increment_if(counts, "weak_setup_quality_advisory", weak_setup)
        _increment_if(counts, "weak_setup_quality_but_approved", weak_setup and approved)
        _increment_if(counts, "portfolio_negative_advisory", portfolio_negative)
        _increment_if(counts, "portfolio_negative_but_approved", portfolio_negative and approved)
        _increment_if(counts, "portfolio_block_advisory", portfolio_block)
        _increment_if(counts, "portfolio_size_down_advisory", portfolio_size_down)
        _increment_if(counts, "execution_quality_negative_advisory", execution_negative)
        _increment_if(
            counts, "execution_quality_negative_but_approved", execution_negative and approved
        )
        _increment_if(counts, "execution_quality_block_advisory", execution_block)
        _increment_if(counts, "execution_quality_size_down_advisory", execution_size_down)

        if approved and (
            dp_block
            or ml_negative
            or session_would_block
            or weak_setup
            or portfolio_negative
            or execution_negative
        ):
            examples.append(
                {
                    "time": row.get("decision_time"),
                    "symbol": row.get("symbol"),
                    "action": row.get("action"),
                    "signals": ",".join(
                        label
                        for label, condition in (
                            ("decision_policy_block", dp_block),
                            ("ml_negative_compare", ml_negative),
                            ("session_would_block", session_would_block),
                            ("weak_setup_quality", weak_setup),
                            ("portfolio_negative", portfolio_negative),
                            ("execution_quality_negative", execution_negative),
                        )
                        if condition
                    ),
                }
            )

    print(f"rows                         : {counts['rows']}")
    print(f"buy_rows                     : {counts['buy_rows']}")
    print(f"approved_rows                : {counts['approved_rows']}")
    print()
    print("Authority modes")
    for mode, n in sorted(mode_counts.items()):
        print(f"  {mode:<32} {n:5d}")

    print()
    print("ML authority modes (BUY rows)")
    for mode, n in sorted(ml_mode_counts.items()):
        print(f"  {mode:<32} {n:5d}")

    print()
    print("Advisory disagreement counts")
    for key in (
        "decision_policy_block_advisory",
        "decision_policy_block_but_approved",
        "decision_policy_size_down_advisory",
        "decision_policy_size_down_not_applied",
        "ml_negative_compare_advisory",
        "ml_negative_compare_but_approved",
        "ml_negative_compare_ignored_by_design",
        "ml_negative_compare_would_block_under_promoted_mode",
        "ml_authority_triggered",
        "ml_authority_size_down",
        "ml_authority_block_enforced",
        "session_would_block_advisory",
        "session_would_block_but_approved",
        "weak_setup_quality_advisory",
        "weak_setup_quality_but_approved",
        "portfolio_negative_advisory",
        "portfolio_negative_but_approved",
        "portfolio_block_advisory",
        "portfolio_size_down_advisory",
        "execution_quality_negative_advisory",
        "execution_quality_negative_but_approved",
        "execution_quality_block_advisory",
        "execution_quality_size_down_advisory",
    ):
        print(f"  {key:<42} {counts[key]:5d}")

    print()
    print("ML authority promotion checklist")
    for key in (
        "ml_authority_qualified",
        "ml_authority_not_enforced_due_to_mode",
        "ml_authority_live_block_refused",
        "ml_authority_block_enforced",
        "ml_authority_size_down",
    ):
        print(f"  {key:<42} {counts[key]:5d}")

    if examples:
        print()
        print("Approved rows with advisory-negative signals")
        for item in examples[:20]:
            print(
                f"  {str(item['time'])[:19]:<19} "
                f"{str(item['symbol'] or '-'):<6} "
                f"{str(item['action'] or '-'):<4} "
                f"{item['signals']}"
            )

    print()
    print("[OK] advisory authority report completed")
    return True
