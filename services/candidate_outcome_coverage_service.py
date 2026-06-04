"""Shared candidate-universe forward-outcome coverage helpers."""

from __future__ import annotations

import json
from typing import Any, Iterable


FORWARD_OUTCOME_KEYS = (
    "forward_return_pct",
    "return_60m",
    "return_30m",
    "return_eod",
    "forward_mfe_pct",
    "max_favorable_60m",
    "max_favorable_30m",
    "max_favorable_eod",
)

NON_TAKEN_STATUSES = {
    "near_threshold",
    "scored_not_taken",
    "skipped",
    "watch",
    "exit_considered_not_taken",
}


def load_candidate_json(raw: Any) -> dict[str, Any]:
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        loaded = json.loads(str(raw))
        return loaded if isinstance(loaded, dict) else {}
    except Exception:
        return {}


def candidate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    nested = payload.get("candidate")
    return nested if isinstance(nested, dict) else payload


def candidate_has_forward_outcome(payload: dict[str, Any]) -> bool:
    return any(payload.get(key) is not None for key in FORWARD_OUTCOME_KEYS)


def _rate(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(count / total, 4)


def _is_non_taken(row: dict[str, Any]) -> bool:
    status = str(row.get("candidate_status") or "").strip().lower()
    decision = str(row.get("decision") or "").strip().lower()
    if status == "taken" or decision in {"submitted", "approved", "buy"}:
        return False
    return status in NON_TAKEN_STATUSES or bool(status or decision)


def summarize_candidate_outcome_coverage(
    candidate_rows: Iterable[dict[str, Any]],
) -> dict[str, Any]:
    rows = [dict(row) for row in candidate_rows]
    by_status: dict[str, int] = {}
    by_status_with_forward: dict[str, int] = {}
    rows_with_forward = 0
    non_taken_rows = 0
    non_taken_with_forward = 0

    for row in rows:
        status = str(row.get("candidate_status") or "unknown")
        by_status[status] = by_status.get(status, 0) + 1
        payload = load_candidate_json(row.get("candidate_json"))
        has_forward = candidate_has_forward_outcome(payload)
        if has_forward:
            rows_with_forward += 1
            by_status_with_forward[status] = by_status_with_forward.get(status, 0) + 1
        if _is_non_taken(row):
            non_taken_rows += 1
            if has_forward:
                non_taken_with_forward += 1

    missing = len(rows) - rows_with_forward
    non_taken_missing = non_taken_rows - non_taken_with_forward
    return {
        "rows": len(rows),
        "rows_with_forward_outcome": rows_with_forward,
        "missing_forward_outcome": missing,
        "forward_outcome_coverage_rate": _rate(rows_with_forward, len(rows)),
        "non_taken_rows": non_taken_rows,
        "non_taken_with_forward_outcome": non_taken_with_forward,
        "non_taken_missing_forward_outcome": non_taken_missing,
        "non_taken_forward_outcome_coverage_rate": _rate(
            non_taken_with_forward,
            non_taken_rows,
        ),
        "taken_rows": by_status.get("taken", 0),
        "near_threshold_rows": by_status.get("near_threshold", 0),
        "scored_not_taken_rows": by_status.get("scored_not_taken", 0),
        "exit_considered_not_taken_rows": by_status.get("exit_considered_not_taken", 0),
        "by_status": dict(sorted(by_status.items())),
        "by_status_with_forward_outcome": dict(sorted(by_status_with_forward.items())),
    }
