"""Offline comparison for standard vs asymmetric advanced-alpha filters."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from typing import Any, Iterable

ADVANCED_ALPHA_COMPARISON_VERSION = "advanced_alpha_model_comparison_v1"
ADVANCED_ALPHA_COMPARISON_RUNTIME_EFFECT = "diagnostic_only_no_live_authority"


@dataclass(frozen=True)
class ModelComparisonProfile:
    name: str
    trades_taken: int
    true_positives: int
    false_positives: int
    win_rate: float | None
    avg_forward_return_pct: float | None
    net_return_units: float
    max_drawdown_units: float
    sharpe_proxy: float | None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class AdvancedAlphaModelComparisonPayload:
    report_version: str
    runtime_effect: str
    rows: int
    rows_with_outcome: int
    profiles: list[ModelComparisonProfile]
    summary: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "report_version": self.report_version,
            "runtime_effect": self.runtime_effect,
            "rows": self.rows,
            "rows_with_outcome": self.rows_with_outcome,
            "profiles": [profile.to_dict() for profile in self.profiles],
            "summary": self.summary,
        }


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(float(value))
    except Exception:
        return None


def _rate(count: int, total: int) -> float | None:
    if total <= 0:
        return None
    return round(count / total, 4)


def _mean(values: list[float]) -> float | None:
    if not values:
        return None
    return round(sum(values) / len(values), 4)


def _max_drawdown(values: list[float]) -> float:
    peak = 0.0
    equity = 0.0
    drawdown = 0.0
    for value in values:
        equity += value
        peak = max(peak, equity)
        drawdown = max(drawdown, peak - equity)
    return round(drawdown, 4)


def _sharpe_proxy(values: list[float]) -> float | None:
    if len(values) < 2:
        return None
    avg = sum(values) / len(values)
    variance = sum((value - avg) ** 2 for value in values) / (len(values) - 1)
    std = math.sqrt(variance)
    if std <= 0:
        return None
    return round(avg / std * math.sqrt(len(values)), 4)


def _success(row: dict[str, Any]) -> bool | None:
    triple = _int(row.get("triple_barrier_label"))
    if triple is not None:
        return triple == 1
    forward = _float(row.get("forward_return_pct"))
    if forward is None:
        return None
    return forward > 0


def _standard_takes(row: dict[str, Any]) -> bool:
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
    return True


def _profile(name: str, rows: list[dict[str, Any]], predicate) -> ModelComparisonProfile:
    returns: list[float] = []
    successes = 0
    failures = 0
    for row in rows:
        if not predicate(row):
            continue
        success = _success(row)
        if success is None:
            continue
        if success:
            successes += 1
        else:
            failures += 1
        returns.append(_float(row.get("forward_return_pct")) or 0.0)
    trades = successes + failures
    return ModelComparisonProfile(
        name=name,
        trades_taken=trades,
        true_positives=successes,
        false_positives=failures,
        win_rate=_rate(successes, trades),
        avg_forward_return_pct=_mean(returns),
        net_return_units=round(sum(returns), 4),
        max_drawdown_units=_max_drawdown(returns),
        sharpe_proxy=_sharpe_proxy(returns),
    )


def build_advanced_alpha_model_comparison_payload(
    rows: Iterable[dict[str, Any]],
) -> AdvancedAlphaModelComparisonPayload:
    normalized = [dict(row) for row in rows]
    outcome_rows = [row for row in normalized if _success(row) is not None]
    standard = _profile("standard_score_threshold", outcome_rows, _standard_takes)
    asymmetric = _profile("asymmetric_false_positive_guard", outcome_rows, _asymmetric_takes)
    fp_delta = standard.false_positives - asymmetric.false_positives
    dd_delta = round(standard.max_drawdown_units - asymmetric.max_drawdown_units, 4)
    sharpe_delta = None
    if standard.sharpe_proxy is not None and asymmetric.sharpe_proxy is not None:
        sharpe_delta = round(asymmetric.sharpe_proxy - standard.sharpe_proxy, 4)

    return AdvancedAlphaModelComparisonPayload(
        report_version=ADVANCED_ALPHA_COMPARISON_VERSION,
        runtime_effect=ADVANCED_ALPHA_COMPARISON_RUNTIME_EFFECT,
        rows=len(normalized),
        rows_with_outcome=len(outcome_rows),
        profiles=[standard, asymmetric],
        summary={
            "false_positive_reduction": fp_delta,
            "drawdown_reduction_units": dd_delta,
            "sharpe_proxy_delta": sharpe_delta,
            "asymmetric_takes_fewer_or_equal_trades": (
                asymmetric.trades_taken <= standard.trades_taken
            ),
            "authority_ready": False,
        },
    )
