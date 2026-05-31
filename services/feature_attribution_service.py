"""Feature-family attribution over canonical lifecycle rows.

This report is deliberately diagnostic. It estimates whether newly collected
feature families add realized expectancy information after the old gates have
already produced lifecycle rows. It does not create approval or sizing authority.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
from typing import Any, Iterable


FEATURE_FAMILIES: dict[str, tuple[str, ...]] = {
    "market_regime": ("regime_state", "market_regime"),
    "execution_quality": ("regime_state", "execution_quality_decision"),
    "portfolio_decision": ("regime_state", "portfolio_decision"),
    "market_microstructure": ("regime_state", "breakout_quality"),
    "market_participation": ("regime_state", "participation_state"),
    "volatility_normalization": ("regime_state", "volatility_chase_risk"),
    "setup_structure": ("setup_state", "structure_state"),
    "downside_asymmetry": ("regime_state", "downside_state"),
    "utility_estimate": (
        "advisory_authority_state",
        "utility_estimate",
        "utility_decision",
    ),
}

INTERACTION_FIELDS: dict[str, tuple[str, ...]] = {
    "setup_label": ("setup_state", "label"),
    "regime": ("regime_state", "market_regime"),
    "session_phase": ("regime_state", "session_phase"),
}


@dataclass(frozen=True)
class FeatureAttributionPayload:
    summary: dict[str, Any]
    families: list[dict[str, Any]]
    rollout_guardrails: list[dict[str, Any]]


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


def _path(data: dict[str, Any], path: tuple[str, ...], default: str = "unknown") -> Any:
    cur: Any = data
    for key in path:
        if not isinstance(cur, dict):
            return default
        cur = cur.get(key)
    if cur in (None, ""):
        return default
    return cur


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


def _rate(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(count / total, 4)


def _outcome(row: dict[str, Any]) -> float | None:
    if row.get("approved"):
        return _float(row.get("realized_return_pct"))
    return _float(row.get("rejected_return_60m") or row.get("rejected_return_30m"))


def _mfe(row: dict[str, Any]) -> float | None:
    if row.get("approved"):
        return _float(row.get("mfe_pct"))
    return _float(row.get("rejected_max_favorable_60m"))


def _mae(row: dict[str, Any]) -> float | None:
    if row.get("approved"):
        return _float(row.get("max_adverse_excursion_pct"))
    return _float(row.get("rejected_max_adverse_60m"))


def _canonical(row: dict[str, Any]) -> dict[str, Any]:
    cached = row.get("_canonical")
    if isinstance(cached, dict):
        return cached
    canonical = _load_json(row.get("canonical_intelligence_json"))
    row["_canonical"] = canonical
    return canonical


def _bucket(row: dict[str, Any], path: tuple[str, ...]) -> str:
    return str(_path(_canonical(row), path))


def _base_metrics(rows: list[dict[str, Any]]) -> dict[str, Any]:
    outcomes = [_outcome(row) for row in rows]
    outcomes = [value for value in outcomes if value is not None]
    mfe_values = [_mfe(row) for row in rows]
    mfe_values = [value for value in mfe_values if value is not None]
    mae_values = [_mae(row) for row in rows]
    mae_values = [value for value in mae_values if value is not None]
    return {
        "sample_size": len(outcomes),
        "hit_rate": _rate(sum(1 for value in outcomes if value > 0), len(outcomes)),
        "ev_pct": _mean(outcomes),
        "mfe_pct": _mean(mfe_values),
        "mae_pct": _mean(mae_values),
    }


def _bucket_metrics(
    *,
    family_rows: list[dict[str, Any]],
    all_rows: list[dict[str, Any]],
    bucket_name: str,
    family_path: tuple[str, ...],
) -> dict[str, Any]:
    metrics = _base_metrics(family_rows)
    baseline = _base_metrics(all_rows)
    hit = metrics["hit_rate"]
    base_hit = baseline["hit_rate"]
    ev = metrics["ev_pct"]
    base_ev = baseline["ev_pct"]
    mfe = metrics["mfe_pct"]
    base_mfe = baseline["mfe_pct"]
    mae = metrics["mae_pct"]
    base_mae = baseline["mae_pct"]
    rejected_rows = [row for row in family_rows if not row.get("approved")]
    approved_rows = [row for row in family_rows if row.get("approved")]
    baseline_rejected_rows = [row for row in all_rows if not row.get("approved")]
    baseline_approved_rows = [row for row in all_rows if row.get("approved")]
    rejected_outcomes = [_outcome(row) for row in rejected_rows]
    rejected_outcomes = [value for value in rejected_outcomes if value is not None]
    approved_outcomes = [_outcome(row) for row in approved_rows]
    approved_outcomes = [value for value in approved_outcomes if value is not None]
    baseline_rejected_outcomes = [_outcome(row) for row in baseline_rejected_rows]
    baseline_rejected_outcomes = [
        value for value in baseline_rejected_outcomes if value is not None
    ]
    baseline_approved_outcomes = [_outcome(row) for row in baseline_approved_rows]
    baseline_approved_outcomes = [
        value for value in baseline_approved_outcomes if value is not None
    ]
    false_positive_rate = _rate(
        sum(1 for value in approved_outcomes if value <= 0),
        len(approved_outcomes),
    )
    baseline_false_positive_rate = _rate(
        sum(1 for value in baseline_approved_outcomes if value <= 0),
        len(baseline_approved_outcomes),
    )
    false_negative_rate = _rate(
        sum(1 for value in rejected_outcomes if value > 0),
        len(rejected_outcomes),
    )
    baseline_false_negative_rate = _rate(
        sum(1 for value in baseline_rejected_outcomes if value > 0),
        len(baseline_rejected_outcomes),
    )

    interactions = {}
    for name, path in INTERACTION_FIELDS.items():
        counts: dict[str, int] = {}
        for row in family_rows:
            key = str(_path(_canonical(row), path))
            counts[key] = counts.get(key, 0) + 1
        interactions[name] = [
            {"bucket": key, "count": count}
            for key, count in sorted(counts.items(), key=lambda item: (-item[1], item[0]))[:5]
        ]

    return {
        "bucket": bucket_name,
        **metrics,
        "hit_rate_delta": (
            round(hit - base_hit, 4)
            if hit is not None and base_hit is not None
            else None
        ),
        "ev_delta_pct": (
            round(ev - base_ev, 4)
            if ev is not None and base_ev is not None
            else None
        ),
        "mfe_delta_pct": (
            round(mfe - base_mfe, 4)
            if mfe is not None and base_mfe is not None
            else None
        ),
        "mae_delta_pct": (
            round(mae - base_mae, 4)
            if mae is not None and base_mae is not None
            else None
        ),
        "false_positive_rate": false_positive_rate,
        "false_negative_rate": false_negative_rate,
        "false_positive_reduction": (
            round(baseline_false_positive_rate - false_positive_rate, 4)
            if baseline_false_positive_rate is not None and false_positive_rate is not None
            else None
        ),
        "false_negative_increase": (
            round(false_negative_rate - baseline_false_negative_rate, 4)
            if baseline_false_negative_rate is not None and false_negative_rate is not None
            else None
        ),
        "interactions": interactions,
        "feature_path": ".".join(family_path),
    }


def _rollout_guardrail(family: dict[str, Any], *, min_sample_size: int) -> dict[str, Any]:
    best = family.get("best_bucket") or {}
    worst = family.get("worst_bucket") or {}
    sample_size = int(family.get("covered_rows") or 0)
    missing_rate = float(family.get("missing_rate") or 0.0)
    ev_spread = None
    if best.get("ev_pct") is not None and worst.get("ev_pct") is not None:
        ev_spread = round(float(best["ev_pct"]) - float(worst["ev_pct"]), 4)
    stable_enough = sample_size >= min_sample_size and missing_rate <= 0.20
    return {
        "family": family["family"],
        "sample_size": sample_size,
        "min_sample_size": min_sample_size,
        "missing_rate": missing_rate,
        "ev_spread_pct": ev_spread,
        "status": "eligible_for_review" if stable_enough else "insufficient_evidence",
        "required_before_authority": [
            "rolling_window_stability",
            "acceptable_calibration_error",
            "replay_validation",
        ],
    }


def build_feature_attribution_payload(
    rows: Iterable[dict[str, Any]],
    *,
    min_sample_size: int = 30,
) -> FeatureAttributionPayload:
    rows_list = [dict(row) for row in rows]
    outcome_rows = [row for row in rows_list if _outcome(row) is not None]
    baseline = _base_metrics(outcome_rows)
    families: list[dict[str, Any]] = []

    for family, path in FEATURE_FAMILIES.items():
        grouped: dict[str, list[dict[str, Any]]] = {}
        for row in outcome_rows:
            grouped.setdefault(_bucket(row, path), []).append(row)

        buckets = [
            _bucket_metrics(
                family_rows=family_rows,
                all_rows=outcome_rows,
                bucket_name=bucket,
                family_path=path,
            )
            for bucket, family_rows in grouped.items()
        ]
        buckets.sort(
            key=lambda item: (
                item["bucket"] == "unknown",
                -(item.get("sample_size") or 0),
                item["bucket"],
            )
        )
        known = [item for item in buckets if item["bucket"] != "unknown"]
        best = max(known, key=lambda item: item.get("ev_pct") or -999.0, default={})
        worst = min(known, key=lambda item: item.get("ev_pct") or 999.0, default={})
        covered = sum(item["sample_size"] for item in known)
        missing = len(outcome_rows) - covered
        family_payload = {
            "family": family,
            "feature_path": ".".join(path),
            "rows_with_outcome": len(outcome_rows),
            "covered_rows": covered,
            "missing_rows": missing,
            "missing_rate": round(missing / len(outcome_rows), 4) if outcome_rows else None,
            "best_bucket": best,
            "worst_bucket": worst,
            "buckets": buckets,
        }
        families.append(family_payload)

    guardrails = [
        _rollout_guardrail(family, min_sample_size=min_sample_size)
        for family in families
    ]
    return FeatureAttributionPayload(
        summary={
            "rows": len(rows_list),
            "rows_with_outcome": len(outcome_rows),
            "baseline": baseline,
            "min_sample_size": min_sample_size,
            "authority_note": "diagnostic_only_no_live_authority",
        },
        families=families,
        rollout_guardrails=guardrails,
    )
