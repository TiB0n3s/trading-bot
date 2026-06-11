"""Observe-only shadow scoring for candidate ML artifacts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from repositories.shadow_prediction_repo import ShadowPredictionRepository
from services.prediction_cache_service import sanitize_prediction_outputs

from ml_platform.config import MODEL_REGISTRY_PATH
from ml_platform.registry import load_registry

SHADOW_REPORT_VERSION = "shadow_prediction_run_v1"
SHADOW_HEALTH_REPORT_VERSION = "shadow_prediction_health_v1"
SHADOW_CANDIDATE_STATUSES = ("candidate", "shadow", "observe_only")


@dataclass(frozen=True)
class ShadowModelSelection:
    model_id: str
    artifact_path: str
    status: str
    created_at: str | None


def _parse_iso(value: Any) -> datetime:
    if not value:
        return datetime.min.replace(tzinfo=timezone.utc)
    try:
        text = str(value)
        if text.endswith("Z"):
            text = text[:-1] + "+00:00"
        parsed = datetime.fromisoformat(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return datetime.min.replace(tzinfo=timezone.utc)


class ShadowPredictionService:
    def __init__(
        self,
        *,
        repository: ShadowPredictionRepository,
        registry_path: Path | str = MODEL_REGISTRY_PATH,
    ):
        self.repository = repository
        self.registry_path = Path(registry_path)

    def select_candidate_model(self) -> ShadowModelSelection | None:
        registry = load_registry(self.registry_path)
        candidates = []
        for model in registry.get("models") or []:
            status = str(model.get("status") or "").lower()
            artifact_path = str(model.get("artifact_path") or "")
            if status not in SHADOW_CANDIDATE_STATUSES or not artifact_path:
                continue
            if not Path(artifact_path).exists():
                continue
            candidates.append(model)
        if not candidates:
            return None
        candidates.sort(
            key=lambda item: _parse_iso(item.get("updated_at") or item.get("created_at")),
            reverse=True,
        )
        selected = candidates[0]
        return ShadowModelSelection(
            model_id=str(selected.get("model_id")),
            artifact_path=str(selected.get("artifact_path")),
            status=str(selected.get("status")),
            created_at=selected.get("created_at"),
        )

    def _load_artifact(self, artifact_path: str) -> dict[str, Any] | None:
        try:
            import joblib

            artifact = joblib.load(artifact_path)
            if isinstance(artifact, dict) and artifact.get("model"):
                return artifact
        except Exception:
            return None
        return None

    def run(
        self,
        *,
        market_date: str,
        limit: int = 500,
    ) -> dict[str, Any]:
        selected = self.select_candidate_model()
        if not selected:
            return {
                "report_version": SHADOW_REPORT_VERSION,
                "runtime_effect": "observe_only_no_live_authority",
                "status": "skipped_no_candidate_model",
                "market_date": market_date,
                "rows_written": 0,
            }
        artifact = self._load_artifact(selected.artifact_path)
        if not artifact:
            return {
                "report_version": SHADOW_REPORT_VERSION,
                "runtime_effect": "observe_only_no_live_authority",
                "status": "skipped_unreadable_artifact",
                "market_date": market_date,
                "model_id": selected.model_id,
                "artifact_path": selected.artifact_path,
                "rows_written": 0,
            }
        metadata = artifact.get("metadata") or {}
        feature_columns = list(metadata.get("feature_columns") or [])
        if not feature_columns:
            return {
                "report_version": SHADOW_REPORT_VERSION,
                "runtime_effect": "observe_only_no_live_authority",
                "status": "skipped_missing_feature_columns",
                "market_date": market_date,
                "model_id": selected.model_id,
                "rows_written": 0,
            }
        feature_rows = self.repository.latest_feature_rows(
            market_date=market_date,
            feature_columns=feature_columns,
            limit=limit,
        )
        if not feature_rows:
            return {
                "report_version": SHADOW_REPORT_VERSION,
                "runtime_effect": "observe_only_no_live_authority",
                "status": "skipped_no_feature_rows",
                "market_date": market_date,
                "model_id": selected.model_id,
                "rows_written": 0,
            }

        model = artifact["model"]
        matrix = [[float(row.get(col) or 0.0) for col in feature_columns] for row in feature_rows]
        raw_scores = []
        try:
            probabilities = model.predict_proba(matrix)
            for item in probabilities:
                raw_scores.append(float(item[1]) * 100.0)
        except Exception:
            predictions = model.predict(matrix)
            for item in predictions:
                raw_scores.append(float(item) * 100.0)

        generated_at = datetime.now(timezone.utc).isoformat()
        rows = []
        for feature_row, raw_score in zip(feature_rows, raw_scores):
            sanitized = sanitize_prediction_outputs({"prediction_score": raw_score})
            rows.append(
                {
                    "market_date": market_date,
                    "symbol": str(feature_row.get("symbol") or "").upper(),
                    "prediction_time": feature_row.get("timestamp"),
                    "model_id": selected.model_id,
                    "artifact_path": selected.artifact_path,
                    "prediction_score": sanitized.get("prediction_score"),
                    "raw_prediction_score": raw_score,
                    "feature_snapshot_id": feature_row.get("id"),
                    "feature_available_at": feature_row.get("feature_available_at"),
                    "generated_at": generated_at,
                    "runtime_effect": "shadow_only_no_live_authority",
                }
            )
        changed = self.repository.upsert_shadow_predictions(rows)
        return {
            "report_version": SHADOW_REPORT_VERSION,
            "runtime_effect": "observe_only_no_live_authority",
            "status": "completed",
            "market_date": market_date,
            "model_id": selected.model_id,
            "artifact_path": selected.artifact_path,
            "feature_row_count": len(feature_rows),
            "rows_written": changed,
        }

    def health_report(
        self,
        *,
        market_date: str,
        shadow_approve_threshold: float = 55.0,
        max_divergence_rate: float = 0.35,
        min_comparable_rows: int = 10,
        limit: int = 1000,
    ) -> dict[str, Any]:
        rows = self.repository.load_shadow_authority_comparison(
            market_date=market_date,
            shadow_approve_threshold=shadow_approve_threshold,
            limit=limit,
        )
        comparable = [row for row in rows if row.get("runtime_decision") is not None]
        divergences = [
            row
            for row in comparable
            if str(row.get("shadow_decision")) != str(row.get("runtime_decision"))
        ]
        comparable_count = len(comparable)
        divergence_rate = len(divergences) / comparable_count if comparable_count else None
        agreement_rate = 1.0 - divergence_rate if divergence_rate is not None else None
        alert = bool(
            comparable_count >= int(min_comparable_rows)
            and divergence_rate is not None
            and divergence_rate > float(max_divergence_rate)
        )
        return {
            "report_version": SHADOW_HEALTH_REPORT_VERSION,
            "runtime_effect": "shadow_health_monitor_no_order_authority",
            "market_date": market_date,
            "status": "divergence_alert" if alert else "ok",
            "rows": len(rows),
            "comparable_rows": comparable_count,
            "divergence_rows": len(divergences),
            "divergence_rate": (round(divergence_rate, 6) if divergence_rate is not None else None),
            "agreement_rate": round(agreement_rate, 6) if agreement_rate is not None else None,
            "thresholds": {
                "shadow_approve_threshold": shadow_approve_threshold,
                "max_divergence_rate": max_divergence_rate,
                "min_comparable_rows": min_comparable_rows,
            },
            "promotion_certified": bool(
                comparable_count >= int(min_comparable_rows)
                and divergence_rate is not None
                and divergence_rate <= float(max_divergence_rate)
            ),
            "sample_divergences": divergences[:10],
        }
