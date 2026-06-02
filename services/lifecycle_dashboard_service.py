"""Default decision lifecycle dashboard over canonical analysis rows."""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Any, Iterable


LIFECYCLE_DASHBOARD_REPORT_VERSION = "lifecycle_dashboard_v1"


@dataclass(frozen=True)
class LifecycleDashboardPayload:
    summary: dict[str, Any]
    status_counts: list[dict[str, Any]]
    decision_path_counts: list[dict[str, Any]]
    exit_trigger_counts: list[dict[str, Any]]
    top_missed_rejections: list[dict[str, Any]]
    lifecycle_rows: list[dict[str, Any]]


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _count_rows(counter: Counter) -> list[dict[str, Any]]:
    return [
        {"bucket": key, "count": count}
        for key, count in sorted(counter.items(), key=lambda item: (-item[1], item[0]))
    ]


def build_lifecycle_dashboard_payload(
    rows: Iterable[dict[str, Any]],
    *,
    samples: int = 15,
) -> LifecycleDashboardPayload:
    rows_list = [dict(row) for row in rows]
    status_counts: Counter[str] = Counter()
    decision_paths: Counter[str] = Counter()
    exit_triggers: Counter[str] = Counter()
    approved_returns: list[float] = []
    rejected_returns: list[float] = []
    rejected_missing = 0
    rejected_snapshot_only = 0
    approved_missing_exit = 0
    top_missed: list[dict[str, Any]] = []

    for row in rows_list:
        status = str(row.get("lifecycle_status") or "unknown")
        status_counts[status] += 1
        decision_paths[
            f"{row.get('action') or 'unknown'} -> {row.get('final_decision') or 'unknown'} -> {status}"
        ] += 1

        if row.get("approved"):
            if row.get("exit_snapshot_id"):
                exit_triggers[str(row.get("exit_trigger") or "unknown")] += 1
            else:
                approved_missing_exit += 1
            realized = _float(row.get("realized_return_pct"))
            if realized is not None:
                approved_returns.append(realized)
            continue

        if status == "rejected_snapshot_only_no_trade":
            rejected_snapshot_only += 1
            continue

        rejected_return = _float(
            row.get("rejected_return_60m")
            or row.get("rejected_return_30m")
            or row.get("rejected_return_eod")
        )
        rejected_mfe = _float(row.get("rejected_max_favorable_60m"))
        if rejected_return is None and rejected_mfe is None:
            rejected_missing += 1
            continue
        if rejected_return is not None:
            rejected_returns.append(rejected_return)
        if rejected_mfe is not None and rejected_mfe > 0:
            top_missed.append(
                {
                    "decision_time": row.get("decision_time"),
                    "symbol": row.get("symbol"),
                    "rejection_reason": row.get("rejection_reason"),
                    "rejected_return_60m": rejected_return,
                    "rejected_return_eod": row.get("rejected_return_eod"),
                    "rejected_max_favorable_60m": rejected_mfe,
                    "setup_label": row.get("setup_label"),
                    "market_regime": row.get("market_regime"),
                    "session_phase": row.get("session_phase"),
                }
            )

    top_missed.sort(
        key=lambda item: (
            -float(item.get("rejected_max_favorable_60m") or 0.0),
            str(item.get("decision_time") or ""),
        )
    )

    summary = {
        "report_version": LIFECYCLE_DASHBOARD_REPORT_VERSION,
        "runtime_effect": "diagnostic_only_no_live_authority",
        "rows": len(rows_list),
        "approved_rows": sum(1 for row in rows_list if row.get("approved")),
        "rejected_rows": sum(1 for row in rows_list if not row.get("approved")),
        "approved_exit_link_gaps": approved_missing_exit,
        "rejected_snapshot_only_rows": rejected_snapshot_only,
        "rejected_forward_outcome_gaps": rejected_missing,
        "approved_avg_return_pct": _mean(approved_returns),
        "rejected_counterfactual_avg_return_pct": _mean(rejected_returns),
        "analysis_ready": approved_missing_exit == 0 and rejected_missing == 0,
    }

    return LifecycleDashboardPayload(
        summary=summary,
        status_counts=_count_rows(status_counts),
        decision_path_counts=_count_rows(decision_paths),
        exit_trigger_counts=_count_rows(exit_triggers),
        top_missed_rejections=top_missed[:samples],
        lifecycle_rows=rows_list[:samples],
    )
