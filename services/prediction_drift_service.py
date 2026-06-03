"""Structured prediction drift checks for ML retraining automation.

This service is diagnostic only. It never changes runtime authority, order
approval, sizing, or broker behavior.
"""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

from repositories.prediction_drift_repo import PredictionDriftRepository


PREDICTION_DRIFT_REPORT_VERSION = "prediction_drift_v1"


@dataclass(frozen=True)
class PredictionDateCorrelation:
    market_date: str
    pair_count: int
    correlation: float | None
    status: str
    reason: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class PredictionDriftReport:
    report_version: str
    runtime_effect: str
    target_date: str | None
    sessions_requested: int
    bad_session_limit: int
    flat_or_negative_threshold: float
    min_pairs_per_session: int
    date_scores: list[PredictionDateCorrelation] = field(default_factory=list)
    coverage_status: str = "unknown"
    latest_available_date: str | None = None
    missing_requested_session_count: int = 0
    bad_session_count: int = 0
    valid_session_count: int = 0
    average_correlation: float | None = None
    warning: bool = False
    retraining_recommended: bool = False
    reason: str = ""

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["date_scores"] = [score.to_dict() for score in self.date_scores]
        return payload


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        result = float(value)
        if math.isnan(result) or math.isinf(result):
            return None
        return result
    except Exception:
        return None


def _pearson(xs: list[float], ys: list[float]) -> float | None:
    if len(xs) < 2 or len(ys) < 2 or len(xs) != len(ys):
        return None
    mean_x = sum(xs) / len(xs)
    mean_y = sum(ys) / len(ys)
    num = sum((x - mean_x) * (y - mean_y) for x, y in zip(xs, ys))
    den_x = math.sqrt(sum((x - mean_x) ** 2 for x in xs))
    den_y = math.sqrt(sum((y - mean_y) ** 2 for y in ys))
    if den_x <= 0.0 or den_y <= 0.0:
        return 0.0
    return round(num / (den_x * den_y), 4)


class PredictionDriftService:
    def __init__(self, *, repository: PredictionDriftRepository):
        self.repository = repository

    def correlation_report(
        self,
        *,
        target_date: str | None = None,
        sessions: int = 5,
        threshold: float = 0.0,
        bad_session_limit: int = 3,
        min_pairs_per_session: int = 3,
    ) -> PredictionDriftReport:
        sessions = max(1, int(sessions))
        bad_session_limit = max(1, int(bad_session_limit))
        min_pairs_per_session = max(2, int(min_pairs_per_session))
        dates = self.repository.available_prediction_outcome_dates(
            target_date=target_date,
            limit=sessions,
        )
        scores: list[PredictionDateCorrelation] = []
        for market_date in dates:
            pairs = self.repository.prediction_outcome_pairs(market_date)
            xs: list[float] = []
            ys: list[float] = []
            for row in pairs:
                score = _float(row.get("prediction_score"))
                outcome = _float(row.get("session_return_pct"))
                if score is None or outcome is None:
                    continue
                xs.append(score)
                ys.append(outcome)
            pair_count = len(xs)
            if pair_count < min_pairs_per_session:
                scores.append(
                    PredictionDateCorrelation(
                        market_date=market_date,
                        pair_count=pair_count,
                        correlation=None,
                        status="insufficient_pairs",
                        reason=f"need at least {min_pairs_per_session} prediction/outcome pairs",
                    )
                )
                continue
            corr = _pearson(xs, ys)
            status = "directional" if corr is not None and corr > threshold else "flat_or_negative"
            reason = (
                "prediction_score has positive directional correlation"
                if status == "directional"
                else "prediction_score correlation is flat or negative"
            )
            scores.append(
                PredictionDateCorrelation(
                    market_date=market_date,
                    pair_count=pair_count,
                    correlation=corr,
                    status=status,
                    reason=reason,
                )
            )

        valid = [score for score in scores if score.correlation is not None]
        bad = [score for score in valid if (score.correlation or 0.0) <= threshold]
        missing_requested_session_count = max(0, sessions - len(scores))
        avg = (
            round(sum(float(score.correlation) for score in valid) / len(valid), 4)
            if valid
            else None
        )
        warning = len(bad) >= bad_session_limit
        if not scores:
            coverage_status = "no_prediction_outcome_data"
            reason = "no joined prediction/outcome rows found"
        elif not valid:
            coverage_status = "insufficient_pairs"
            reason = "prediction/outcome rows exist but no session has enough pairs"
        elif len(valid) < min(sessions, bad_session_limit):
            coverage_status = "partial"
            reason = "partial prediction/outcome coverage; not enough valid sessions for a strong drift conclusion"
        elif warning:
            coverage_status = "evaluated"
            reason = (
                f"{len(bad)} sessions have prediction_score correlation <= {threshold}"
            )
        else:
            coverage_status = "evaluated"
            reason = "prediction_score directional correlation is not in retraining-alert state"
        return PredictionDriftReport(
            report_version=PREDICTION_DRIFT_REPORT_VERSION,
            runtime_effect="diagnostic_only_no_live_authority",
            target_date=target_date,
            sessions_requested=sessions,
            bad_session_limit=bad_session_limit,
            flat_or_negative_threshold=threshold,
            min_pairs_per_session=min_pairs_per_session,
            date_scores=scores,
            coverage_status=coverage_status,
            latest_available_date=scores[0].market_date if scores else None,
            missing_requested_session_count=missing_requested_session_count,
            bad_session_count=len(bad),
            valid_session_count=len(valid),
            average_correlation=avg,
            warning=warning,
            retraining_recommended=warning,
            reason=reason,
        )


def build_default_prediction_drift_service(
    db_path: Path | str | None = None,
) -> PredictionDriftService:
    kwargs: dict[str, Any] = {}
    if db_path is not None:
        kwargs["db_path"] = db_path
    return PredictionDriftService(
        repository=PredictionDriftRepository(**kwargs)
    )
