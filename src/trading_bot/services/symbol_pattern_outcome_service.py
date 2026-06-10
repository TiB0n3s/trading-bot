"""Outcome and rollout diagnostics for observe-only symbol patterns."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable

SYMBOL_PATTERN_OUTCOME_REPORT_VERSION = "symbol_pattern_outcomes_v1"
PATTERN_RUNTIME_EFFECT = "diagnostic_only_no_live_authority"


@dataclass(frozen=True)
class SymbolPatternOutcomePayload:
    summary: dict[str, Any]
    pattern_outcomes: list[dict[str, Any]]
    calibration_buckets: list[dict[str, Any]]
    quality_warnings: list[dict[str, Any]]
    rollout_governance: list[dict[str, Any]]
    exit_patterns: list[dict[str, Any]]


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


def _rate(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(count / total, 4)


def _outcome(row: dict[str, Any]) -> float | None:
    if row.get("approved"):
        return _float(row.get("realized_return_pct"))
    return _float(
        row.get("rejected_return_60m")
        or row.get("rejected_return_30m")
        or row.get("rejected_return_eod")
    )


def _mfe(row: dict[str, Any]) -> float | None:
    if row.get("approved"):
        return _float(row.get("mfe_pct"))
    return _float(row.get("rejected_max_favorable_60m"))


def _mae(row: dict[str, Any]) -> float | None:
    if row.get("approved"):
        return _float(row.get("max_adverse_excursion_pct"))
    return _float(row.get("rejected_max_adverse_60m"))


def _metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes = [_outcome(row) for row in rows]
    outcomes = [value for value in outcomes if value is not None]
    mfe_values = [_mfe(row) for row in rows]
    mfe_values = [value for value in mfe_values if value is not None]
    mae_values = [_mae(row) for row in rows]
    mae_values = [value for value in mae_values if value is not None]
    approved_rows = [row for row in rows if row.get("approved")]
    approved_outcomes = [_outcome(row) for row in approved_rows]
    approved_outcomes = [value for value in approved_outcomes if value is not None]
    approved_with_mfe = [
        row for row in approved_rows if _mfe(row) is not None and _outcome(row) is not None
    ]
    winner_became_loser = [
        row for row in approved_with_mfe if (_mfe(row) or 0) > 0 and (_outcome(row) or 0) <= 0
    ]
    capture = [_float(row.get("capture_ratio")) for row in approved_rows]
    capture = [value for value in capture if value is not None]
    missed = [_float(row.get("missed_upside_pct")) for row in approved_rows]
    missed = [value for value in missed if value is not None]
    avoided = [_float(row.get("avoided_drawdown_pct")) for row in approved_rows]
    avoided = [value for value in avoided if value is not None]
    return {
        "sample_size": len(outcomes),
        "approved_count": len(approved_rows),
        "rejected_count": len(rows) - len(approved_rows),
        "hit_rate": _rate(sum(1 for value in outcomes if value > 0), len(outcomes)),
        "ev_pct": _mean(outcomes),
        "mfe_pct": _mean(mfe_values),
        "mae_pct": _mean(mae_values),
        "approved_false_positive_rate": _rate(
            sum(1 for value in approved_outcomes if value <= 0),
            len(approved_outcomes),
        ),
        "winner_became_loser_rate": _rate(
            len(winner_became_loser),
            len(approved_with_mfe),
        ),
        "avg_capture_ratio": _mean(capture),
        "avg_missed_upside_pct": _mean(missed),
        "avg_avoided_drawdown_pct": _mean(avoided),
    }


def _baseline(rows: list[dict[str, Any]]) -> dict[str, Any]:
    return _metrics(rows)


def _group(rows: list[dict[str, Any]], key_fn) -> dict[str, list[dict[str, Any]]]:
    grouped: dict[str, list[dict[str, Any]]] = {}
    for row in rows:
        grouped.setdefault(key_fn(row), []).append(row)
    return grouped


def _pattern_outcomes(rows: list[dict[str, Any]], baseline: dict[str, Any]) -> list[dict[str, Any]]:
    result = []
    for pattern, pattern_rows in _group(rows, lambda row: _bucket(row, "symbol_pattern")).items():
        metrics = _metrics(pattern_rows)
        ev = metrics.get("ev_pct")
        base_ev = baseline.get("ev_pct")
        hit = metrics.get("hit_rate")
        base_hit = baseline.get("hit_rate")
        result.append(
            {
                "pattern": pattern,
                **metrics,
                "ev_delta_pct": round(ev - base_ev, 4)
                if ev is not None and base_ev is not None
                else None,
                "hit_rate_delta": round(hit - base_hit, 4)
                if hit is not None and base_hit is not None
                else None,
                "source_mix": _source_mix(pattern_rows),
            }
        )
    result.sort(
        key=lambda item: (
            -(item.get("sample_size") or 0),
            str(item.get("pattern") or ""),
        )
    )
    return result


def _source_mix(rows: list[dict[str, Any]]) -> dict[str, int]:
    counts: dict[str, int] = {}
    for row in rows:
        source = _bucket(row, "pattern_source", "unknown")
        counts[source] = counts.get(source, 0) + 1
    return dict(sorted(counts.items()))


def _calibration_buckets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    interactions = [
        ("market_regime", "market_regime"),
        ("setup_label", "setup_label"),
        ("session_phase", "session_phase"),
        ("execution_cost_bucket", "execution_cost_bucket"),
        ("volatility_chase_risk", "volatility_chase_risk"),
    ]
    result = []
    for interaction_name, field in interactions:
        grouped = _group(
            rows,
            lambda row, field=field: f"{_bucket(row, 'symbol_pattern')} x {_bucket(row, field)}",
        )
        for bucket, bucket_rows in grouped.items():
            metrics = _metrics(bucket_rows)
            result.append(
                {
                    "interaction": interaction_name,
                    "bucket": bucket,
                    **metrics,
                }
            )
    result.sort(
        key=lambda item: (
            item["interaction"],
            -(item.get("sample_size") or 0),
            item["bucket"],
        )
    )
    return result


def _quality_warnings(
    rows: list[dict[str, Any]], pattern_outcomes: list[dict[str, Any]]
) -> list[dict[str, Any]]:
    warnings = []
    total = len(rows)
    if not total:
        return [
            {
                "warning": "no_rows",
                "severity": "warn",
                "reason": "no lifecycle rows available for symbol-pattern diagnostics",
            }
        ]

    unclassified = sum(
        1
        for row in rows
        if _bucket(row, "symbol_pattern") in {"mixed_or_unclassified_pattern", "unknown"}
    )
    derived = sum(
        1 for row in rows if _bucket(row, "pattern_source") == "derived_from_canonical_sections"
    )
    missing_effect = sum(1 for row in rows if _bucket(row, "pattern_runtime_effect") == "unknown")
    distinct_patterns = {
        _bucket(row, "symbol_pattern")
        for row in rows
        if _bucket(row, "symbol_pattern") != "unknown"
    }
    unclassified_rate = unclassified / total
    derived_rate = derived / total
    if unclassified_rate >= 0.50:
        warnings.append(
            {
                "warning": "high_unclassified_pattern_rate",
                "severity": "warn",
                "rate": round(unclassified_rate, 4),
                "reason": "pattern labels are not discriminating enough for promotion",
            }
        )
    if derived_rate >= 0.50:
        warnings.append(
            {
                "warning": "high_read_time_backfill_rate",
                "severity": "info",
                "rate": round(derived_rate, 4),
                "reason": "many rows use deterministic read-time pattern derivation",
            }
        )
    if missing_effect:
        warnings.append(
            {
                "warning": "missing_runtime_effect",
                "severity": "warn",
                "count": missing_effect,
                "reason": "pattern rows should remain explicitly observe-only",
            }
        )
    if len(distinct_patterns) <= 1 and total >= 20:
        warnings.append(
            {
                "warning": "low_pattern_diversity",
                "severity": "warn",
                "distinct_patterns": len(distinct_patterns),
                "reason": "patternization is not separating the lifecycle population",
            }
        )
    thin = [
        item["pattern"]
        for item in pattern_outcomes
        if (item.get("sample_size") or 0) < 30
        and item["pattern"] not in {"mixed_or_unclassified_pattern", "unknown"}
    ]
    if thin:
        warnings.append(
            {
                "warning": "thin_pattern_samples",
                "severity": "info",
                "patterns": thin[:8],
                "reason": "non-default pattern samples need more outcomes before promotion",
            }
        )
    return warnings


def _governance(
    pattern_outcomes: list[dict[str, Any]], *, min_sample_size: int
) -> list[dict[str, Any]]:
    result = []
    for item in pattern_outcomes:
        pattern = item["pattern"]
        blockers = []
        sample_size = int(item.get("sample_size") or 0)
        ev = item.get("ev_pct")
        false_positive = item.get("approved_false_positive_rate")
        if sample_size < min_sample_size:
            blockers.append(f"sample_size<{min_sample_size}")
        if pattern in {"mixed_or_unclassified_pattern", "unknown"}:
            blockers.append("default_or_unknown_pattern")
        if ev is None:
            blockers.append("missing_ev")
        if false_positive is None:
            blockers.append("missing_false_positive_rate")

        status = "observe_only"
        if blockers:
            status = "not_ready"
        elif ev is not None and ev <= -0.30 and (false_positive or 0) >= 0.50:
            status = "narrow_block_candidate"
        elif ev is not None and ev <= -0.10:
            status = "size_down_candidate"

        result.append(
            {
                "pattern": pattern,
                "status": status,
                "runtime_effect": PATTERN_RUNTIME_EFFECT,
                "sample_size": sample_size,
                "ev_pct": ev,
                "false_positive_rate": false_positive,
                "blockers": blockers,
                "reason": (
                    "diagnostic candidate only; no live authority is wired"
                    if status != "not_ready"
                    else "; ".join(blockers)
                ),
            }
        )
    return result


def _exit_patterns(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    approved = [row for row in rows if row.get("approved")]
    grouped = _group(
        approved,
        lambda row: f"{_bucket(row, 'symbol_pattern')} x exit={_bucket(row, 'exit_trigger')}",
    )
    result = []
    for bucket, bucket_rows in grouped.items():
        metrics = _metrics(bucket_rows)
        result.append({"bucket": bucket, **metrics})
    result.sort(key=lambda item: (-(item.get("sample_size") or 0), item["bucket"]))
    return result


def build_symbol_pattern_outcome_payload(
    rows: Iterable[dict[str, Any]],
    *,
    min_sample_size: int = 30,
) -> SymbolPatternOutcomePayload:
    rows_list = [dict(row) for row in rows]
    rows_with_outcome = [row for row in rows_list if _outcome(row) is not None]
    baseline = _baseline(rows_with_outcome)
    outcomes = _pattern_outcomes(rows_with_outcome, baseline)
    warnings = _quality_warnings(rows_list, outcomes)
    summary = {
        "report_version": SYMBOL_PATTERN_OUTCOME_REPORT_VERSION,
        "runtime_effect": PATTERN_RUNTIME_EFFECT,
        "rows": len(rows_list),
        "rows_with_outcome": len(rows_with_outcome),
        "pattern_rows": sum(1 for row in rows_list if _bucket(row, "symbol_pattern") != "unknown"),
        "distinct_patterns": len(
            {
                _bucket(row, "symbol_pattern")
                for row in rows_list
                if _bucket(row, "symbol_pattern") != "unknown"
            }
        ),
        "baseline": baseline,
        "min_sample_size": min_sample_size,
    }
    return SymbolPatternOutcomePayload(
        summary=summary,
        pattern_outcomes=outcomes,
        calibration_buckets=_calibration_buckets(rows_with_outcome),
        quality_warnings=warnings,
        rollout_governance=_governance(outcomes, min_sample_size=min_sample_size),
        exit_patterns=_exit_patterns(rows_with_outcome),
    )
