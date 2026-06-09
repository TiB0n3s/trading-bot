"""Population Stability Index drift governance for self-adjusting models."""

from __future__ import annotations

import math
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from policy_artifacts import atomic_write_json

from ml_platform.config import MODEL_ROOT, ensure_ml_dirs
from repositories.concept_drift_repo import ConceptDriftRepository

CONCEPT_DRIFT_REPORT_VERSION = "concept_drift_psi_v1"
DEFAULT_DRIFT_ARTIFACT_PATH = MODEL_ROOT / "veto_relaxation_v1" / "concept_drift.json"
DEFAULT_SEVERE_PSI_THRESHOLD = 0.25
DEFAULT_FEATURES = (
    "vpin_toxicity_20",
    "cvd_price_corr_20",
    "fractional_diff_zscore_20",
    "range_atr_ratio",
    "atr_20_pct",
    "volume_ratio_20",
    "trend_scan_tstat",
)


@dataclass(frozen=True)
class ConceptDriftReport:
    report_version: str
    runtime_effect: str
    target_date: str
    baseline_window: dict[str, str]
    recent_window: dict[str, str]
    severe_psi_threshold: float
    features: list[dict[str, Any]]
    severe_drift: bool
    max_psi: float | None
    action: str
    generated_at: str
    artifact_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _date_days_before(date_text: str, days: int) -> str:
    parsed = datetime.fromisoformat(date_text).date()
    return (parsed - timedelta(days=days)).isoformat()


def _quantile(values: list[float], q: float) -> float:
    if not values:
        return 0.0
    ordered = sorted(values)
    idx = min(len(ordered) - 1, max(0, int(round((len(ordered) - 1) * q))))
    return ordered[idx]


def _bins_from_baseline(values: list[float], buckets: int) -> list[float]:
    if len(values) < 2:
        return []
    edges = [_quantile(values, i / buckets) for i in range(1, buckets)]
    deduped: list[float] = []
    for edge in edges:
        if not deduped or edge > deduped[-1]:
            deduped.append(edge)
    return deduped


def _bucket_counts(values: list[float], edges: list[float]) -> list[int]:
    counts = [0 for _ in range(len(edges) + 1)]
    for value in values:
        idx = 0
        while idx < len(edges) and value > edges[idx]:
            idx += 1
        counts[idx] += 1
    return counts


def population_stability_index(
    baseline: list[float],
    recent: list[float],
    *,
    buckets: int = 10,
    epsilon: float = 1e-6,
) -> float | None:
    if len(baseline) < 20 or len(recent) < 10:
        return None
    edges = _bins_from_baseline(baseline, buckets)
    if not edges:
        return None
    base_counts = _bucket_counts(baseline, edges)
    recent_counts = _bucket_counts(recent, edges)
    base_total = max(1, sum(base_counts))
    recent_total = max(1, sum(recent_counts))
    psi = 0.0
    for base_count, recent_count in zip(base_counts, recent_counts):
        expected = max(epsilon, base_count / base_total)
        actual = max(epsilon, recent_count / recent_total)
        psi += (actual - expected) * math.log(actual / expected)
    return round(psi, 6)


class ConceptDriftService:
    def __init__(self, *, repository: ConceptDriftRepository):
        self.repository = repository

    def psi_report(
        self,
        *,
        target_date: str,
        baseline_start: str = "2024-06-01",
        recent_days: int = 5,
        features: tuple[str, ...] = DEFAULT_FEATURES,
        severe_threshold: float = DEFAULT_SEVERE_PSI_THRESHOLD,
        artifact_path: Path | str | None = DEFAULT_DRIFT_ARTIFACT_PATH,
    ) -> ConceptDriftReport:
        recent_start = _date_days_before(target_date, max(1, recent_days - 1))
        feature_rows: list[dict[str, Any]] = []
        for feature in features:
            baseline = self.repository.feature_values(
                table_name="bar_pattern_features",
                feature=feature,
                start_date=baseline_start,
                end_date=target_date,
            )
            recent = self.repository.feature_values(
                table_name="bar_pattern_features",
                feature=feature,
                start_date=recent_start,
                end_date=target_date,
            )
            psi = population_stability_index(baseline, recent)
            if psi is None:
                status = "insufficient_data_or_missing_feature"
            elif psi >= severe_threshold:
                status = "severe_drift"
            elif psi >= 0.10:
                status = "moderate_drift"
            else:
                status = "stable"
            feature_rows.append(
                {
                    "feature": feature,
                    "baseline_rows": len(baseline),
                    "recent_rows": len(recent),
                    "psi": psi,
                    "status": status,
                }
            )
        scored = [row for row in feature_rows if row.get("psi") is not None]
        max_psi = max((float(row["psi"]) for row in scored), default=None)
        severe = any(str(row.get("status")) == "severe_drift" for row in feature_rows)
        action = (
            "disable_counterfactual_veto_relaxation_until_retraining"
            if severe
            else "allow_counterfactual_veto_relaxation"
        )
        report = ConceptDriftReport(
            report_version=CONCEPT_DRIFT_REPORT_VERSION,
            runtime_effect="paper_model_drift_guardrail",
            target_date=target_date,
            baseline_window={"start": baseline_start, "end": target_date},
            recent_window={"start": recent_start, "end": target_date},
            severe_psi_threshold=severe_threshold,
            features=feature_rows,
            severe_drift=severe,
            max_psi=round(max_psi, 6) if max_psi is not None else None,
            action=action,
            generated_at=datetime.now(timezone.utc).isoformat(),
            artifact_path=str(artifact_path) if artifact_path else None,
        )
        if artifact_path:
            ensure_ml_dirs()
            path = Path(artifact_path)
            path.parent.mkdir(parents=True, exist_ok=True)
            atomic_write_json(path, report.to_dict())
        return report


def build_default_concept_drift_service(
    db_path: Path | str | None = None,
) -> ConceptDriftService:
    kwargs: dict[str, Any] = {}
    if db_path is not None:
        kwargs["db_path"] = db_path
    return ConceptDriftService(repository=ConceptDriftRepository(**kwargs))
