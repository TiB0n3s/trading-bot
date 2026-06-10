"""Read-only friction heatmap for LSI-aware model comparison."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable

FRICTION_HEATMAP_VERSION = "friction_heatmap_v1"
FRICTION_HEATMAP_RUNTIME_EFFECT = "diagnostic_only_no_live_authority"

_BUCKET_ORDER = ("normal", "moderate", "elevated", "severe", "unknown")


@dataclass(frozen=True)
class FrictionHeatmapCell:
    profile: str
    liquidity_stress_bucket: str
    rows: int
    trades_taken: int
    stopouts: int
    toxic_stopouts: int
    avg_lsi_score: float | None
    avg_forward_return_pct: float | None
    stopout_rate: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class FrictionHeatmapPayload:
    report_version: str
    runtime_effect: str
    rows: int
    rows_with_outcome: int
    heatmap: list[FrictionHeatmapCell]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "runtime_effect": self.runtime_effect,
            "rows": self.rows,
            "rows_with_outcome": self.rows_with_outcome,
            "heatmap": [cell.to_dict() for cell in self.heatmap],
            "summary": self.summary,
        }


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        result = float(value)
    except Exception:
        return None
    if not math.isfinite(result):
        return None
    return result


def _int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except Exception:
        return None


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _rate(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(count / total, 4)


def _success(row: dict[str, Any]) -> bool | None:
    triple = _int(row.get("triple_barrier_label"))
    if triple is not None:
        return triple == 1
    forward = _float(row.get("forward_return_pct"))
    if forward is None:
        return None
    return forward > 0


def _liquidity_stress_score(row: dict[str, Any]) -> float | None:
    explicit = _float(row.get("liquidity_stress_score"))
    if explicit is not None:
        return _clamp(explicit)

    components: list[float] = []
    vpin = _float(row.get("vpin_toxicity_20"))
    if vpin is not None:
        components.append(_clamp(vpin * 100.0))
    spread = _float(row.get("bid_ask_spread_pct"))
    if spread is not None:
        components.append(_clamp(spread * 80.0))
    slippage = _float(row.get("slippage_estimate_pct"))
    if slippage is not None:
        components.append(_clamp(slippage * 120.0))
    sweep = _float(row.get("liquidity_sweep_risk"))
    if sweep is not None:
        components.append(_clamp(sweep * 100.0))

    if not components:
        return None
    return round(sum(components) / len(components), 4)


def _lsi_bucket(row: dict[str, Any]) -> str:
    explicit = str(row.get("liquidity_stress_bucket") or "").strip().lower()
    if explicit in _BUCKET_ORDER:
        return explicit
    score = _liquidity_stress_score(row)
    if score is None:
        return "unknown"
    if score >= 70:
        return "severe"
    if score >= 45:
        return "elevated"
    if score >= 20:
        return "moderate"
    return "normal"


def _toxic_flow(row: dict[str, Any]) -> bool:
    vpin = _float(row.get("vpin_toxicity_20"))
    if vpin is not None and vpin >= 0.90:
        return True
    return _lsi_bucket(row) in {"elevated", "severe"}


def _symmetric_takes(row: dict[str, Any]) -> bool:
    score = _float(row.get("long_opportunity_score"))
    return bool(score is not None and score >= 50.0)


def _asymmetric_takes(row: dict[str, Any]) -> bool:
    score = _float(row.get("long_opportunity_score"))
    if score is None or score < 70.0:
        return False
    if _int(row.get("trend_scan_label")) == -1:
        return False
    if str(row.get("cvd_divergence_label") or "").lower() == "bearish_distribution":
        return False
    vpin = _float(row.get("vpin_toxicity_20"))
    if vpin is not None and vpin >= 0.90:
        return False
    return _lsi_bucket(row) != "severe"


def _cell(
    *,
    profile: str,
    bucket: str,
    rows: list[dict[str, Any]],
    predicate,
) -> FrictionHeatmapCell:
    bucket_rows = [row for row in rows if _lsi_bucket(row) == bucket]
    taken = [row for row in bucket_rows if predicate(row)]
    outcome_rows = [row for row in taken if _success(row) is not None]
    stopouts = [row for row in outcome_rows if _success(row) is False]
    toxic_stopouts = [row for row in stopouts if _toxic_flow(row)]
    returns = [
        value
        for value in (_float(row.get("forward_return_pct")) for row in outcome_rows)
        if value is not None
    ]
    scores = [
        value
        for value in (_liquidity_stress_score(row) for row in bucket_rows)
        if value is not None
    ]
    return FrictionHeatmapCell(
        profile=profile,
        liquidity_stress_bucket=bucket,
        rows=len(bucket_rows),
        trades_taken=len(outcome_rows),
        stopouts=len(stopouts),
        toxic_stopouts=len(toxic_stopouts),
        avg_lsi_score=_mean(scores),
        avg_forward_return_pct=_mean(returns),
        stopout_rate=_rate(len(stopouts), len(outcome_rows)),
    )


def build_friction_heatmap_payload(
    rows: Iterable[dict[str, Any]],
) -> FrictionHeatmapPayload:
    normalized = [dict(row) for row in rows]
    outcome_rows = [row for row in normalized if _success(row) is not None]
    profiles = {
        "symmetric_score_threshold": _symmetric_takes,
        "asymmetric_lsi_guard": _asymmetric_takes,
    }
    heatmap = [
        _cell(profile=profile, bucket=bucket, rows=outcome_rows, predicate=predicate)
        for profile, predicate in profiles.items()
        for bucket in _BUCKET_ORDER
    ]

    symmetric_bad = [
        row
        for row in outcome_rows
        if _symmetric_takes(row) and _success(row) is False and _toxic_flow(row)
    ]
    avoided = [row for row in symmetric_bad if not _asymmetric_takes(row)]
    scaled_down = [
        row
        for row in outcome_rows
        if _asymmetric_takes(row) and _lsi_bucket(row) in {"moderate", "elevated"}
    ]

    return FrictionHeatmapPayload(
        report_version=FRICTION_HEATMAP_VERSION,
        runtime_effect=FRICTION_HEATMAP_RUNTIME_EFFECT,
        rows=len(normalized),
        rows_with_outcome=len(outcome_rows),
        heatmap=heatmap,
        summary={
            "symmetric_toxic_stopouts": len(symmetric_bad),
            "asymmetric_toxic_stopouts_avoided": len(avoided),
            "asymmetric_lsi_scale_down_candidates": len(scaled_down),
            "authority_ready": False,
        },
    )
