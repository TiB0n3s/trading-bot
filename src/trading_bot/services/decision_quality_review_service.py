"""Outcome-centric decision quality review.

This service is diagnostic-only.  It converts lifecycle rows into plain
learning labels so reviews can focus on trade quality instead of binary gates.
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable

DECISION_QUALITY_REVIEW_VERSION = "decision_quality_review_v1"
RUNTIME_EFFECT = "diagnostic_only_no_live_authority"


@dataclass(frozen=True)
class DecisionQualityReviewPayload:
    summary: dict[str, Any]
    quality_counts: list[dict[str, Any]]
    learning_action_counts: list[dict[str, Any]]
    rows: list[dict[str, Any]]


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _bucket(row: dict[str, Any], key: str, default: str = "unknown") -> str:
    value = row.get(key)
    if value in (None, ""):
        return default
    return str(value)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _rejected_return(row: dict[str, Any]) -> float | None:
    return _float(
        row.get("rejected_return_60m")
        or row.get("rejected_return_30m")
        or row.get("rejected_return_eod")
    )


def _approved_quality(row: dict[str, Any]) -> tuple[str, list[str], str]:
    realized = _float(row.get("realized_return_pct"))
    mfe = _float(row.get("mfe_pct"))
    mae = _float(row.get("max_adverse_excursion_pct"))
    capture = _float(row.get("capture_ratio"))
    missed = _float(row.get("missed_upside_pct"))

    if realized is None:
        return (
            "approved_missing_outcome",
            ["complete_exit_snapshot_linkage"],
            "approved row has no realized outcome",
        )

    if realized > 0 and capture is not None and capture >= 0.65:
        return (
            "excellent_entry_exit",
            ["reinforce_entry_exit_pattern"],
            f"captured {capture:.2f} of MFE with realized {realized:.2f}%",
        )

    if realized > 0 and mfe is not None and mfe >= 0.50 and capture is not None and capture < 0.40:
        actions = ["improve_peak_capture"]
        if missed is not None and missed >= 0.40:
            actions.append("review_missed_upside_after_exit")
        return (
            "good_entry_weak_exit",
            actions,
            f"trade won but capture was {capture:.2f} after MFE {mfe:.2f}%",
        )

    if realized <= 0 and mfe is not None and mfe >= 0.50:
        return (
            "good_entry_poor_exit",
            ["tighten_peak_lock_or_exit_timing"],
            f"trade reached MFE {mfe:.2f}% but closed {realized:.2f}%",
        )

    if realized <= 0 and (mfe is None or mfe < 0.25):
        actions = ["improve_entry_filter_or_timing"]
        if mae is not None and mae <= -0.50:
            actions.append("review_downside_asymmetry")
        return (
            "bad_entry_or_no_edge",
            actions,
            f"trade never produced enough MFE; realized {realized:.2f}%",
        )

    if realized > 0:
        return (
            "acceptable_trade",
            ["collect_more_context_before_tuning"],
            f"profitable but not peak-quality; realized {realized:.2f}%",
        )

    return (
        "weak_or_inconclusive_trade",
        ["collect_more_context_before_tuning"],
        f"realized {realized:.2f}% with insufficient quality signal",
    )


def _rejected_quality(row: dict[str, Any]) -> tuple[str, list[str], str]:
    action = str(row.get("action") or "").strip().lower()
    final_decision = str(row.get("final_decision") or "").strip().lower()
    if action == "sell" and final_decision in {"no_replace_now", "hold", "observe"}:
        return (
            "exit_hold_observation",
            ["add_exit_hold_forward_outcomes"],
            f"sell-side observation chose {final_decision or 'no action'}",
        )

    forward_return = _rejected_return(row)
    forward_mfe = _float(row.get("rejected_max_favorable_60m"))
    forward_mae = _float(row.get("rejected_max_adverse_60m"))

    if forward_return is None and forward_mfe is None:
        return (
            "rejected_missing_forward_outcome",
            ["backfill_rejected_forward_outcomes"],
            "rejected row has no counterfactual forward outcome",
        )

    if (forward_mfe is not None and forward_mfe >= 0.80) or (
        forward_return is not None and forward_return >= 0.40
    ):
        return (
            "missed_high_quality_opportunity",
            ["reduce_false_negative_gate_or_entry_timing"],
            f"rejected row later reached MFE {forward_mfe} / return {forward_return}",
        )

    if forward_return is not None and forward_return <= -0.25:
        return (
            "useful_rejection",
            ["reinforce_rejection_pattern"],
            f"rejection avoided forward return {forward_return:.2f}%",
        )

    if forward_mfe is not None and forward_mfe >= 0.35:
        return (
            "missed_partial_opportunity",
            ["review_size_down_instead_of_block"],
            f"rejected row had usable MFE {forward_mfe:.2f}%",
        )

    if forward_mae is not None and forward_mae <= -0.50:
        return (
            "useful_risk_rejection",
            ["reinforce_downside_risk_filter"],
            f"rejection avoided adverse move {forward_mae:.2f}%",
        )

    return (
        "neutral_rejection",
        ["collect_more_context_before_tuning"],
        "counterfactual outcome was small or mixed",
    )


def _review_row(row: dict[str, Any]) -> dict[str, Any]:
    row = dict(row)
    approved = bool(row.get("approved"))
    if approved:
        quality, actions, reason = _approved_quality(row)
        realized = _float(row.get("realized_return_pct"))
        outcome_return = realized
        mfe = _float(row.get("mfe_pct"))
        mae = _float(row.get("max_adverse_excursion_pct"))
    else:
        quality, actions, reason = _rejected_quality(row)
        outcome_return = _rejected_return(row)
        mfe = _float(row.get("rejected_max_favorable_60m"))
        mae = _float(row.get("rejected_max_adverse_60m"))

    return {
        "decision_time": row.get("decision_time"),
        "symbol": row.get("symbol"),
        "action": row.get("action"),
        "approved": approved,
        "final_decision": row.get("final_decision"),
        "quality_label": quality,
        "quality_reason": reason,
        "learning_actions": actions,
        "outcome_return_pct": outcome_return,
        "mfe_pct": mfe,
        "mae_pct": mae,
        "capture_ratio": row.get("capture_ratio"),
        "rejection_reason": row.get("rejection_reason"),
        "exit_trigger": row.get("exit_trigger"),
        "setup_label": row.get("setup_label"),
        "market_regime": row.get("market_regime"),
        "session_phase": row.get("session_phase"),
        "symbol_pattern": row.get("symbol_pattern"),
        "pattern_directional_bias": row.get("pattern_directional_bias"),
        "execution_quality_decision": row.get("execution_quality_decision"),
        "portfolio_decision": row.get("portfolio_decision"),
        "lifecycle_status": row.get("lifecycle_status"),
    }


def _counter_rows(counter: Counter[str]) -> list[dict[str, Any]]:
    return [
        {"bucket": key, "count": count}
        for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def build_decision_quality_review_payload(
    rows: Iterable[dict[str, Any]],
    *,
    samples: int = 20,
) -> DecisionQualityReviewPayload:
    reviewed = [_review_row(dict(row)) for row in rows]
    quality_counts: Counter[str] = Counter()
    action_counts: Counter[str] = Counter()
    approved_returns: list[float] = []
    rejected_returns: list[float] = []
    missing_outcome_rows = 0
    exit_hold_outcome_gaps = 0

    for row in reviewed:
        quality_counts[_bucket(row, "quality_label")] += 1
        for action in row.get("learning_actions") or []:
            action_counts[str(action)] += 1
        outcome = _float(row.get("outcome_return_pct"))
        if outcome is None:
            if row.get("quality_label") == "exit_hold_observation":
                exit_hold_outcome_gaps += 1
                continue
            missing_outcome_rows += 1
            continue
        if row.get("approved"):
            approved_returns.append(outcome)
        else:
            rejected_returns.append(outcome)

    ranked = sorted(
        reviewed,
        key=lambda row: (
            0
            if row["quality_label"]
            in {
                "missed_high_quality_opportunity",
                "good_entry_poor_exit",
                "bad_entry_or_no_edge",
                "good_entry_weak_exit",
            }
            else 1,
            -abs(float(row.get("mfe_pct") or row.get("outcome_return_pct") or 0.0)),
            str(row.get("decision_time") or ""),
        ),
    )

    summary = {
        "report_version": DECISION_QUALITY_REVIEW_VERSION,
        "runtime_effect": RUNTIME_EFFECT,
        "rows": len(reviewed),
        "approved_rows": sum(1 for row in reviewed if row.get("approved")),
        "rejected_rows": sum(1 for row in reviewed if not row.get("approved")),
        "missing_outcome_rows": missing_outcome_rows,
        "exit_hold_outcome_gaps": exit_hold_outcome_gaps,
        "approved_avg_return_pct": _mean(approved_returns),
        "rejected_counterfactual_avg_return_pct": _mean(rejected_returns),
        "excellent_trades": quality_counts.get("excellent_entry_exit", 0),
        "missed_opportunities": quality_counts.get("missed_high_quality_opportunity", 0)
        + quality_counts.get("missed_partial_opportunity", 0),
        "bad_entries_or_no_edge": quality_counts.get("bad_entry_or_no_edge", 0),
        "poor_exit_after_good_entry": quality_counts.get("good_entry_poor_exit", 0),
        "exit_hold_observations": quality_counts.get("exit_hold_observation", 0),
        "analysis_ready": missing_outcome_rows == 0,
    }
    return DecisionQualityReviewPayload(
        summary=summary,
        quality_counts=_counter_rows(quality_counts),
        learning_action_counts=_counter_rows(action_counts),
        rows=ranked[:samples],
    )
