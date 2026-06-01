"""Realized calibration summaries by decision bucket."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable


CALIBRATION_BUCKET_REPORT_VERSION = "calibration_buckets_v1"


@dataclass(frozen=True)
class CalibrationBucketPayload:
    summary: dict[str, Any]
    buckets: list[dict[str, Any]]


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


def _bucket(row: dict[str, Any]) -> str:
    setup = row.get("setup_label") or "unknown_setup"
    regime = row.get("market_regime") or "unknown_regime"
    hour = row.get("decision_hour") or "unknown_hour"
    vol = row.get("volatility_chase_risk") or "unknown_volatility"
    return f"setup={setup} | regime={regime} | hour={hour} | volatility={vol}"


def build_calibration_bucket_payload(
    rows: Iterable[dict[str, Any]],
    *,
    min_sample_size: int = 5,
) -> CalibrationBucketPayload:
    rows_list = [dict(row) for row in rows]
    grouped: dict[str, list[dict[str, Any]]] = {}
    missing_outcome = 0
    for row in rows_list:
        outcome = _outcome(row)
        if outcome is None:
            missing_outcome += 1
            continue
        grouped.setdefault(_bucket(row), []).append(row)

    buckets: list[dict[str, Any]] = []
    for bucket, bucket_rows in grouped.items():
        outcomes = [_outcome(row) for row in bucket_rows]
        outcomes = [value for value in outcomes if value is not None]
        mfes = [_mfe(row) for row in bucket_rows]
        mfes = [value for value in mfes if value is not None]
        maes = [_mae(row) for row in bucket_rows]
        maes = [value for value in maes if value is not None]
        approved = [row for row in bucket_rows if row.get("approved")]
        rejected = [row for row in bucket_rows if not row.get("approved")]
        false_positives = sum(
            1
            for row in approved
            if (_outcome(row) is not None and float(_outcome(row) or 0) <= 0)
        )
        false_negatives = sum(
            1
            for row in rejected
            if (_outcome(row) is not None and float(_outcome(row) or 0) > 0)
        )
        sample_size = len(outcomes)
        buckets.append(
            {
                "bucket": bucket,
                "sample_size": sample_size,
                "min_sample_size": min_sample_size,
                "ready": sample_size >= min_sample_size,
                "win_rate": round(sum(1 for value in outcomes if value > 0) / sample_size, 4)
                if sample_size
                else None,
                "ev_pct": _mean(outcomes),
                "mfe_pct": _mean(mfes),
                "mae_pct": _mean(maes),
                "false_positive_count": false_positives,
                "false_negative_count": false_negatives,
                "false_positive_rate": round(false_positives / len(approved), 4)
                if approved
                else None,
                "false_negative_rate": round(false_negatives / len(rejected), 4)
                if rejected
                else None,
            }
        )

    buckets.sort(key=lambda item: (not item["ready"], -(item["sample_size"] or 0), item["bucket"]))
    return CalibrationBucketPayload(
        summary={
            "report_version": CALIBRATION_BUCKET_REPORT_VERSION,
            "runtime_effect": "diagnostic_only_no_live_authority",
            "rows": len(rows_list),
            "rows_with_outcome": sum(item["sample_size"] for item in buckets),
            "missing_outcome_rows": missing_outcome,
            "bucket_count": len(buckets),
            "ready_bucket_count": sum(1 for item in buckets if item["ready"]),
            "min_sample_size": min_sample_size,
        },
        buckets=buckets,
    )
