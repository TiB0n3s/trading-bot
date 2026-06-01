"""Post-trade learning summaries over lifecycle analysis rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


POST_TRADE_LEARNING_REPORT_VERSION = "post_trade_learning_v1"


@dataclass(frozen=True)
class PostTradeLearningPayload:
    summary: dict[str, Any]
    expectancy_by_dimension: dict[str, list[dict[str, Any]]]
    gate_value: list[dict[str, Any]]
    false_positive_patterns: list[dict[str, Any]]
    false_negative_patterns: list[dict[str, Any]]


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _bucket(row: dict[str, Any], key: str, default: str = "unknown") -> str:
    value = row.get(key)
    if value in (None, ""):
        return default
    return str(value)


def _outcome_return(row: dict[str, Any]) -> float | None:
    if row.get("approved"):
        return _float(row.get("realized_return_pct"))
    return _float(row.get("rejected_return_60m") or row.get("rejected_return_30m"))


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _expectancy_rows(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    buckets: dict[str, list[float]] = {}
    wins: dict[str, int] = {}
    for row in rows:
        outcome = _outcome_return(row)
        if outcome is None:
            continue
        bucket = _bucket(row, key)
        buckets.setdefault(bucket, []).append(outcome)
        if outcome > 0:
            wins[bucket] = wins.get(bucket, 0) + 1
    result = []
    for bucket, values in sorted(buckets.items()):
        result.append(
            {
                "bucket": bucket,
                "count": len(values),
                "avg_return_pct": _mean(values),
                "win_rate": round(wins.get(bucket, 0) / len(values), 4),
            }
        )
    return result


def _pattern_rows(
    rows: list[dict[str, Any]],
    *,
    dimensions: list[str],
    approved: bool,
    profitable: bool,
) -> list[dict[str, Any]]:
    grouped: dict[str, dict[str, Any]] = {}
    for row in rows:
        if bool(row.get("approved")) != approved:
            continue
        outcome = _outcome_return(row)
        if outcome is None:
            continue
        if profitable and outcome <= 0:
            continue
        if not profitable and outcome > 0:
            continue
        parts = [f"{dimension}={_bucket(row, dimension)}" for dimension in dimensions]
        key = " | ".join(parts)
        item = grouped.setdefault(key, {"pattern": key, "count": 0, "outcomes": []})
        item["count"] += 1
        item["outcomes"].append(outcome)

    result = []
    for item in grouped.values():
        outcomes = item.pop("outcomes")
        item["avg_return_pct"] = _mean(outcomes)
        result.append(item)
    result.sort(key=lambda item: (-item["count"], item["pattern"]))
    return result[:20]


def build_post_trade_learning_payload(
    rows: Iterable[dict[str, Any]],
    *,
    dimensions: list[str] | None = None,
) -> PostTradeLearningPayload:
    """Summarize which contexts and gates added or removed value."""
    rows_list = [dict(row) for row in rows]
    dimensions = dimensions or [
        "symbol",
        "rejection_reason",
        "exit_trigger",
        "lifecycle_status",
        "setup_label",
        "market_regime",
        "setup_regime",
        "decision_hour",
        "session_phase",
        "execution_cost_bucket",
        "participation_state",
        "volatility_chase_risk",
        "execution_quality_decision",
        "portfolio_decision",
        "downside_state",
        "utility_decision",
        "confidence_quality",
    ]

    approved_returns: list[float] = []
    rejected_returns: list[float] = []
    missing_outcomes = 0
    for row in rows_list:
        row["setup_regime"] = f"{_bucket(row, 'setup_label')} x {_bucket(row, 'market_regime')}"
        outcome = _outcome_return(row)
        if outcome is None:
            missing_outcomes += 1
            continue
        if row.get("approved"):
            approved_returns.append(outcome)
        else:
            rejected_returns.append(outcome)

    expectancy = {
        dimension: _expectancy_rows(rows_list, dimension)
        for dimension in dimensions
    }

    gate_buckets: dict[str, dict[str, Any]] = {}
    for row in rows_list:
        if row.get("approved"):
            continue
        gate = _bucket(row, "rejection_reason")
        outcome = _outcome_return(row)
        item = gate_buckets.setdefault(
            gate,
            {
                "gate": gate,
                "rejections": 0,
                "missing_outcomes": 0,
                "would_have_helped": 0,
                "would_have_hurt": 0,
                "outcomes": [],
            },
        )
        item["rejections"] += 1
        if outcome is None:
            item["missing_outcomes"] += 1
            continue
        item["outcomes"].append(outcome)
        if outcome <= 0:
            item["would_have_helped"] += 1
        else:
            item["would_have_hurt"] += 1

    gate_value = []
    for item in gate_buckets.values():
        outcomes = item.pop("outcomes")
        item["avg_counterfactual_return_pct"] = _mean(outcomes)
        item["help_rate"] = (
            round(item["would_have_helped"] / len(outcomes), 4)
            if outcomes
            else None
        )
        gate_value.append(item)

    gate_value.sort(key=lambda item: (item["gate"]))
    pattern_dimensions = [
        "setup_label",
        "market_regime",
        "decision_hour",
        "execution_cost_bucket",
        "session_phase",
        "execution_quality_decision",
        "portfolio_decision",
        "downside_state",
    ]
    summary = {
        "report_version": POST_TRADE_LEARNING_REPORT_VERSION,
        "rows": len(rows_list),
        "approved_with_outcomes": len(approved_returns),
        "rejected_with_outcomes": len(rejected_returns),
        "missing_outcomes": missing_outcomes,
        "approved_avg_return_pct": _mean(approved_returns),
        "rejected_counterfactual_avg_return_pct": _mean(rejected_returns),
    }
    return PostTradeLearningPayload(
        summary=summary,
        expectancy_by_dimension=expectancy,
        gate_value=gate_value,
        false_positive_patterns=_pattern_rows(
            rows_list,
            dimensions=pattern_dimensions,
            approved=True,
            profitable=False,
        ),
        false_negative_patterns=_pattern_rows(
            rows_list,
            dimensions=pattern_dimensions,
            approved=False,
            profitable=True,
        ),
    )
