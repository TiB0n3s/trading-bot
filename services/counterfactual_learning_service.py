"""False-negative counterfactual learner for Level-2 veto relaxation."""

from __future__ import annotations

import json
import math
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from policy_artifacts import atomic_write_json

from ml_platform.config import MODEL_ROOT, ensure_ml_dirs
from repositories.counterfactual_training_repo import CounterfactualTrainingRepository

COUNTERFACTUAL_VETO_RELAXATION_VERSION = "counterfactual_veto_relaxation_v1"
DEFAULT_MODEL_DIR = MODEL_ROOT / "veto_relaxation_v1"
DEFAULT_MODEL_PATH = DEFAULT_MODEL_DIR / "veto_relaxation_model.json"
DEFAULT_DRIFT_PATH = DEFAULT_MODEL_DIR / "concept_drift.json"
DEFAULT_PROFIT_BARRIER_PCT = 0.75
DEFAULT_STOP_BARRIER_PCT = -0.50
DEFAULT_UNVETO_THRESHOLD = 0.75
DEFAULT_MAX_RELAXATION_PCT = 10.0

FEATURE_COLUMNS = (
    "master_confidence_score",
    "ensemble_probability",
    "meta_label_threshold",
    "prediction_score",
    "setup_score",
    "ret_1m",
    "ret_5m",
    "ret_15m",
    "range_pos_15m",
    "distance_from_vwap",
    "volume_ratio_5m",
    "relative_strength_5m",
    "spread_pct",
    "momentum_acceleration_pct",
    "volume_surge_ratio",
    "extension_from_recent_base_pct",
    "prior_session_return_pct",
    "candle_body_pct",
    "close_location",
    "range_atr_ratio",
    "atr_20_pct",
    "volume_ratio_20",
    "volume_weighted_pressure_3",
    "cvd_price_corr_20",
    "vpin_toxicity_20",
    "fractional_diff_zscore_20",
    "trend_scan_tstat",
    "pattern_score",
)


@dataclass(frozen=True)
class CounterfactualTrainingResult:
    version: str
    trained: bool
    sample_size: int
    positive_count: int
    positive_rate: float | None
    feature_columns: list[str]
    artifact_path: str | None
    metrics_path: str | None
    reason: str
    generated_at: str
    runtime_effect: str
    guardrail: dict[str, Any]
    metrics: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        parsed = float(value)
    except Exception:
        return None
    return parsed if parsed == parsed else None


def _safe_float(value: Any) -> float:
    parsed = _float(value)
    return parsed if parsed is not None else 0.0


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _path(data: dict[str, Any], *keys: str) -> Any:
    cur: Any = data
    for key in keys:
        if not isinstance(cur, dict):
            return None
        cur = cur.get(key)
    return cur


def _canonical(row: dict[str, Any]) -> dict[str, Any]:
    raw = row.get("canonical_intelligence_json")
    if isinstance(raw, dict):
        return raw
    if not raw:
        return {}
    try:
        loaded = json.loads(str(raw))
    except Exception:
        return {}
    return loaded if isinstance(loaded, dict) else {}


def _canonical_features(row: dict[str, Any]) -> dict[str, Any]:
    canonical = _canonical(row)
    return {
        "master_confidence_score": _path(canonical, "level_2_meta_label", "success_probability")
        or _path(canonical, "historical_bar_paper_strategy", "master_confidence_score"),
        "ensemble_probability": _path(canonical, "level_1_expert_ensemble", "ensemble_probability"),
        "meta_label_threshold": _path(canonical, "level_2_meta_label", "threshold"),
        "prediction_score": _path(canonical, "prediction_state", "ml_score")
        or row.get("prediction_score"),
    }


def relaxation_target(
    row: dict[str, Any],
    *,
    profit_barrier_pct: float = DEFAULT_PROFIT_BARRIER_PCT,
    stop_barrier_pct: float = DEFAULT_STOP_BARRIER_PCT,
) -> int:
    favorable = _float(row.get("max_favorable_60m"))
    adverse = _float(row.get("max_adverse_60m"))
    if favorable is None or adverse is None:
        return 0
    return int(favorable >= profit_barrier_pct and adverse > stop_barrier_pct)


def _feature_row(row: dict[str, Any], feature_columns: tuple[str, ...]) -> list[float]:
    canonical = _canonical_features(row)
    merged = {**row, **canonical}
    values = []
    for col in feature_columns:
        value = merged.get(col)
        if col in {"master_confidence_score", "prediction_score"}:
            parsed = _float(value)
            if parsed is not None and parsed > 1.0:
                value = parsed / 100.0
        values.append(_safe_float(value))
    return values


def _live_feature_row(
    account_state: dict[str, Any], feature_columns: tuple[str, ...]
) -> list[float]:
    historical = account_state.get("historical_bar_paper_strategy") or {}
    ensemble = account_state.get("level_1_expert_ensemble") or {}
    meta = account_state.get("level_2_meta_label") or {}
    prediction = account_state.get("prediction_gate") or {}
    bar = account_state.get("bar_pattern_features") or {}
    micro = account_state.get("microstructure_features") or {}
    merged = {
        **account_state,
        **bar,
        **micro,
        "master_confidence_score": historical.get("master_confidence_score")
        or account_state.get("master_confidence_score"),
        "ensemble_probability": ensemble.get("ensemble_probability")
        or account_state.get("ensemble_probability"),
        "meta_label_threshold": meta.get("threshold") or account_state.get("meta_label_threshold"),
        "prediction_score": prediction.get("ml_prediction_score")
        or prediction.get("prediction_score")
        or account_state.get("prediction_score"),
    }
    values = []
    for col in feature_columns:
        value = merged.get(col)
        if col in {"master_confidence_score", "prediction_score"}:
            parsed = _float(value)
            if parsed is not None and parsed > 1.0:
                value = parsed / 100.0
        values.append(_safe_float(value))
    return values


def _fit_centroid_model(features: list[list[float]], labels: list[int]) -> dict[str, Any]:
    width = len(features[0])
    means = []
    stds = []
    for idx in range(width):
        vals = [row[idx] for row in features]
        mean = sum(vals) / len(vals)
        variance = sum((value - mean) ** 2 for value in vals) / max(1, len(vals) - 1)
        means.append(mean)
        stds.append(math.sqrt(variance) or 1.0)

    scaled = [
        [(value - means[idx]) / stds[idx] for idx, value in enumerate(row)] for row in features
    ]
    positives = [row for row, label in zip(scaled, labels) if label == 1]
    negatives = [row for row, label in zip(scaled, labels) if label == 0]

    def centroid(rows: list[list[float]]) -> list[float]:
        return [sum(row[idx] for row in rows) / len(rows) for idx in range(width)]

    pos_centroid = centroid(positives)
    neg_centroid = centroid(negatives)
    prior = len(positives) / len(labels)
    return {
        "kind": "portable_standardized_centroid_classifier",
        "means": means,
        "stds": stds,
        "positive_centroid": pos_centroid,
        "negative_centroid": neg_centroid,
        "positive_prior": prior,
        "score_scale": 1.5,
    }


def _predict_probability(model: dict[str, Any], values: list[float]) -> float:
    means = model["means"]
    stds = model["stds"]
    scaled = [(value - means[idx]) / (stds[idx] or 1.0) for idx, value in enumerate(values)]

    def distance(center: list[float]) -> float:
        return math.sqrt(sum((value - center[idx]) ** 2 for idx, value in enumerate(scaled)))

    pos_dist = distance(model["positive_centroid"])
    neg_dist = distance(model["negative_centroid"])
    prior = max(0.001, min(0.999, float(model.get("positive_prior") or 0.5)))
    prior_logit = math.log(prior / (1.0 - prior))
    raw = (neg_dist - pos_dist) * float(model.get("score_scale") or 1.0) + prior_logit
    return max(0.0, min(1.0, _sigmoid(raw)))


def _evaluate(
    features: list[list[float]], labels: list[int], model: dict[str, Any]
) -> dict[str, Any]:
    if not labels:
        return {}
    split = max(1, int(len(labels) * 0.8))
    x_test = features[split:] or features
    y_test = labels[split:] or labels
    probabilities = [_predict_probability(model, row) for row in x_test]
    predictions = [1 if prob >= DEFAULT_UNVETO_THRESHOLD else 0 for prob in probabilities]
    tp = sum(1 for actual, pred in zip(y_test, predictions) if actual == 1 and pred == 1)
    fp = sum(1 for actual, pred in zip(y_test, predictions) if actual == 0 and pred == 1)
    tn = sum(1 for actual, pred in zip(y_test, predictions) if actual == 0 and pred == 0)
    fn = sum(1 for actual, pred in zip(y_test, predictions) if actual == 1 and pred == 0)
    total = len(y_test)
    return {
        "validation_method": "chronological_80_20_portable_centroid",
        "validation_rows": total,
        "accuracy": round((tp + tn) / total, 4) if total else None,
        "precision": round(tp / (tp + fp), 4) if (tp + fp) else None,
        "recall": round(tp / (tp + fn), 4) if (tp + fn) else None,
        "false_positive_count": fp,
        "false_negative_count": fn,
    }


def enforce_veto_relaxation_guardrail(
    rows: list[dict[str, Any]],
    *,
    artifact_path: Path | str = DEFAULT_MODEL_PATH,
    min_overruled: int = 5,
    min_win_rate: float = 0.45,
) -> dict[str, Any]:
    """Disable the model when recent overruled trades are underperforming."""
    overruled = []
    for row in rows:
        text = json.dumps(_canonical(row), sort_keys=True).lower()
        reason = str(row.get("rejection_reason") or "").lower()
        if "veto_relaxation" in text or "counterfactual_veto_relaxation" in reason:
            overruled.append(row)
    wins = sum(1 for row in overruled if relaxation_target(row) == 1)
    win_rate = wins / len(overruled) if overruled else None
    disabled = bool(
        len(overruled) >= min_overruled and win_rate is not None and win_rate < min_win_rate
    )
    path = Path(artifact_path)
    if disabled and path.exists():
        path.unlink()
    return {
        "checked": True,
        "overruled_rows": len(overruled),
        "wins": wins,
        "win_rate": round(win_rate, 4) if win_rate is not None else None,
        "min_overruled": min_overruled,
        "min_win_rate": min_win_rate,
        "disabled_model": disabled,
        "artifact_path": str(path),
    }


def train_counterfactual_veto_relaxation_model(
    *,
    rows: list[dict[str, Any]],
    artifact_path: Path | str = DEFAULT_MODEL_PATH,
    min_samples: int = 30,
    min_positive: int = 3,
    profit_barrier_pct: float = DEFAULT_PROFIT_BARRIER_PCT,
    stop_barrier_pct: float = DEFAULT_STOP_BARRIER_PCT,
) -> CounterfactualTrainingResult:
    feature_columns = tuple(FEATURE_COLUMNS)
    labels = [
        relaxation_target(
            row,
            profit_barrier_pct=profit_barrier_pct,
            stop_barrier_pct=stop_barrier_pct,
        )
        for row in rows
    ]
    matrix = [_feature_row(row, feature_columns) for row in rows]
    positives = sum(labels)
    guardrail = enforce_veto_relaxation_guardrail(rows, artifact_path=artifact_path)
    sample_size = len(labels)
    positive_rate = round(positives / sample_size, 4) if sample_size else None
    metrics_path = str(Path(artifact_path).with_suffix(".metrics.json"))

    if guardrail.get("disabled_model"):
        reason = "guardrail disabled model after weak overruled-trade win rate"
        result = CounterfactualTrainingResult(
            version=COUNTERFACTUAL_VETO_RELAXATION_VERSION,
            trained=False,
            sample_size=sample_size,
            positive_count=positives,
            positive_rate=positive_rate,
            feature_columns=list(feature_columns),
            artifact_path=None,
            metrics_path=metrics_path,
            reason=reason,
            generated_at=_now(),
            runtime_effect="paper_veto_relaxation_guardrail",
            guardrail=guardrail,
            metrics={},
        )
        atomic_write_json(Path(metrics_path), result.to_dict())
        return result

    if sample_size < min_samples or positives < min_positive or positives >= sample_size:
        reason = (
            f"insufficient counterfactual rows; need samples>={min_samples}, "
            f"positives>={min_positive}, and both classes"
        )
        result = CounterfactualTrainingResult(
            version=COUNTERFACTUAL_VETO_RELAXATION_VERSION,
            trained=False,
            sample_size=sample_size,
            positive_count=positives,
            positive_rate=positive_rate,
            feature_columns=list(feature_columns),
            artifact_path=None,
            metrics_path=metrics_path,
            reason=reason,
            generated_at=_now(),
            runtime_effect="paper_veto_relaxation_training",
            guardrail=guardrail,
            metrics={},
        )
        atomic_write_json(Path(metrics_path), result.to_dict())
        return result

    model = _fit_centroid_model(matrix, labels)
    metrics = _evaluate(matrix, labels, model)
    artifact = {
        "version": COUNTERFACTUAL_VETO_RELAXATION_VERSION,
        "runtime_effect": "paper_veto_relaxation_model_no_live_order_authority",
        "generated_at": _now(),
        "feature_columns": list(feature_columns),
        "profit_barrier_pct": profit_barrier_pct,
        "stop_barrier_pct": stop_barrier_pct,
        "unveto_threshold": DEFAULT_UNVETO_THRESHOLD,
        "max_relaxation_pct": DEFAULT_MAX_RELAXATION_PCT,
        "sample_size": sample_size,
        "positive_count": positives,
        "positive_rate": positive_rate,
        "model": model,
        "metrics": metrics,
        "guardrail": guardrail,
    }
    ensure_ml_dirs()
    path = Path(artifact_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, artifact)
    result = CounterfactualTrainingResult(
        version=COUNTERFACTUAL_VETO_RELAXATION_VERSION,
        trained=True,
        sample_size=sample_size,
        positive_count=positives,
        positive_rate=positive_rate,
        feature_columns=list(feature_columns),
        artifact_path=str(path),
        metrics_path=metrics_path,
        reason="trained portable counterfactual veto-relaxation classifier",
        generated_at=artifact["generated_at"],
        runtime_effect="paper_veto_relaxation_training",
        guardrail=guardrail,
        metrics=metrics,
    )
    atomic_write_json(Path(metrics_path), result.to_dict())
    return result


def train_from_repository(
    *,
    start_date: str,
    end_date: str,
    db_path: Path | str | None = None,
    artifact_path: Path | str = DEFAULT_MODEL_PATH,
    limit: int = 5000,
    min_samples: int = 30,
) -> CounterfactualTrainingResult:
    repo = (
        CounterfactualTrainingRepository(db_path) if db_path else CounterfactualTrainingRepository()
    )
    rows = repo.fetch_rejected_counterfactual_rows(
        start_date=start_date,
        end_date=end_date,
        limit=limit,
    )
    return train_counterfactual_veto_relaxation_model(
        rows=rows,
        artifact_path=artifact_path,
        min_samples=min_samples,
    )


def evaluate_counterfactual_veto_relaxation(
    *,
    account_state: dict[str, Any],
    artifact_path: Path | str | None = DEFAULT_MODEL_PATH,
    drift_artifact_path: Path | str | None = DEFAULT_DRIFT_PATH,
    enabled: bool = True,
) -> dict[str, Any]:
    if not enabled:
        return {"status": "disabled", "p_unveto": None, "threshold_relaxation_pct": 0.0}
    drift_path = Path(drift_artifact_path or DEFAULT_DRIFT_PATH)
    if drift_path.exists():
        try:
            drift = json.loads(drift_path.read_text())
        except Exception:
            drift = {}
        if drift.get("severe_drift") is True:
            return {
                "status": "concept_drift_disabled",
                "p_unveto": None,
                "threshold_relaxation_pct": 0.0,
                "artifact_path": str(artifact_path or DEFAULT_MODEL_PATH),
                "drift_artifact_path": str(drift_path),
                "max_psi": drift.get("max_psi"),
                "reason": "severe PSI concept drift disables counterfactual veto relaxation",
            }
    path = Path(artifact_path or DEFAULT_MODEL_PATH)
    if not path.exists():
        return {
            "status": "missing_artifact",
            "p_unveto": None,
            "threshold_relaxation_pct": 0.0,
            "artifact_path": str(path),
        }
    try:
        artifact = json.loads(path.read_text())
        feature_columns = tuple(artifact.get("feature_columns") or FEATURE_COLUMNS)
        row = _live_feature_row(account_state, feature_columns)
        p_unveto = _predict_probability(artifact["model"], row)
    except Exception as exc:
        return {
            "status": "artifact_error",
            "p_unveto": None,
            "threshold_relaxation_pct": 0.0,
            "artifact_path": str(path),
            "reason": str(exc),
        }
    threshold = float(artifact.get("unveto_threshold") or DEFAULT_UNVETO_THRESHOLD)
    max_relaxation = float(artifact.get("max_relaxation_pct") or DEFAULT_MAX_RELAXATION_PCT)
    relaxation = max_relaxation * p_unveto if p_unveto >= threshold else 0.0
    return {
        "status": "active",
        "p_unveto": round(p_unveto, 6),
        "threshold": round(threshold, 4),
        "threshold_relaxation_pct": round(relaxation, 4),
        "artifact_path": str(path),
        "reason": (
            "counterfactual learner relaxed Level-2 threshold"
            if relaxation > 0
            else "counterfactual learner did not meet un-veto threshold"
        ),
    }
