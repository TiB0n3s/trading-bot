"""Supervised ML prediction training scaffold over feature snapshots.

This service uses optional sklearn when available and a deterministic baseline
otherwise. It is observe-only and never writes orders or changes live authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from repositories.supervised_prediction_training_repo import (
    fetch_training_rows as repo_fetch_training_rows,
)
from services.optional_dependency_service import optional_dependency_status
from policy_artifacts import atomic_write_json


SUPERVISED_MODEL_VERSION = "supervised_prediction_model_v2"
QUANT_MODEL_SUITE_VERSION = "quant_model_suite_v2"
DEFAULT_FEATURE_COLUMNS = (
    "ret_1m",
    "ret_5m",
    "ret_15m",
    "range_pos_15m",
    "distance_from_vwap",
    "volume_ratio_5m",
    "relative_strength_5m",
    "spread_pct",
    "setup_score",
)
CANDLE_PHYSICS_FEATURE_COLUMNS = (
    "candle_body_pct",
    "upper_wick_pct",
    "lower_wick_pct",
    "upper_lower_wick_ratio",
    "close_location",
    "range_atr_ratio",
    "atr_20_pct",
    "volume_ratio_20",
    "pressure_return_3",
    "pressure_return_8",
    "volume_weighted_pressure_3",
    "pattern_score",
    "long_opportunity_score",
    "sell_opportunity_score",
)
DEFAULT_FEATURE_COLUMNS = DEFAULT_FEATURE_COLUMNS + CANDLE_PHYSICS_FEATURE_COLUMNS
TRIPLE_BARRIER_TARGETS = ("triple_barrier", "triple_barrier_label")


@dataclass(frozen=True)
class SupervisedTrainingResult:
    version: str
    provider: str
    trained: bool
    sample_size: int
    feature_columns: list[str]
    accuracy: float | None
    baseline_positive_rate: float | None
    reason: str
    generated_at: str
    runtime_effect: str
    dependency_status: dict[str, Any]
    artifact_path: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


@dataclass(frozen=True)
class QuantModelSuiteResult:
    version: str
    runtime_effect: str
    horizon: str
    sample_size: int
    feature_columns: list[str]
    models: list[dict[str, Any]]
    best_model: dict[str, Any] | None
    dependency_status: dict[str, Any]
    notes: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _float(value: Any) -> float:
    try:
        return float(value or 0.0)
    except Exception:
        return 0.0


def _row_features(row: dict[str, Any], feature_columns: list[str]) -> list[float]:
    return [_float(row.get(col)) for col in feature_columns]


def _label(row: dict[str, Any], horizon: str) -> int | None:
    if horizon in TRIPLE_BARRIER_TARGETS:
        try:
            value = row.get("triple_barrier_label")
            if value is None:
                return None
            return int(float(value))
        except Exception:
            return None
    col = f"ret_fwd_{horizon}"
    try:
        value = row.get(col)
        if value is None:
            return None
        return 1 if float(value) > 0 else 0
    except Exception:
        return None


def _build_labeled_matrix(
    rows: list[dict[str, Any]],
    *,
    horizon: str,
    feature_columns: list[str],
) -> tuple[list[list[float]], list[int]]:
    labels = []
    features = []
    for row in rows:
        label = _label(row, horizon)
        if label is None:
            continue
        labels.append(label)
        features.append(_row_features(row, feature_columns))
    return features, labels


def _chronological_split(
    features: list[list[float]],
    labels: list[int],
) -> tuple[list[list[float]], list[list[float]], list[int], list[int]]:
    split = max(1, int(len(labels) * 0.8))
    return features[:split], features[split:], labels[:split], labels[split:]


def _accuracy(y_true: list[int], y_pred: list[int]) -> float | None:
    if not y_true:
        return None
    return round(sum(1 for actual, pred in zip(y_true, y_pred) if actual == pred) / len(y_true), 4)


def _model_row(
    *,
    provider: str,
    trained: bool,
    accuracy: float | None,
    reason: str,
    artifact_path: str | None = None,
    baseline_positive_rate: float | None = None,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "trained": trained,
        "accuracy": accuracy,
        "baseline_positive_rate": baseline_positive_rate,
        "reason": reason,
        "artifact_path": artifact_path,
        "runtime_effect": "observe_only_no_live_authority",
    }


def fetch_training_rows(
    *,
    db_path: Path | str | None = None,
    symbol: str | None = None,
    limit: int = 5000,
    prediction_time_cutoff: str | None = None,
) -> list[dict[str, Any]]:
    kwargs: dict[str, Any] = {
        "symbol": symbol,
        "limit": limit,
        "prediction_time_cutoff": prediction_time_cutoff,
    }
    if db_path is not None:
        kwargs["db_path"] = db_path
    return repo_fetch_training_rows(**kwargs)


def train_supervised_prediction_model(
    *,
    rows: list[dict[str, Any]],
    horizon: str = "15m",
    feature_columns: list[str] | None = None,
    min_samples: int = 40,
    artifact_path: Path | str | None = None,
) -> SupervisedTrainingResult:
    feature_columns = list(feature_columns or DEFAULT_FEATURE_COLUMNS)
    features, labels = _build_labeled_matrix(
        rows,
        horizon=horizon,
        feature_columns=feature_columns,
    )

    deps = optional_dependency_status()
    sample_size = len(labels)
    if sample_size < min_samples:
        positive_rate = sum(labels) / sample_size if sample_size else None
        return SupervisedTrainingResult(
            version=SUPERVISED_MODEL_VERSION,
            provider="baseline_insufficient_data",
            trained=False,
            sample_size=sample_size,
            feature_columns=feature_columns,
            accuracy=None,
            baseline_positive_rate=round(positive_rate, 4) if positive_rate is not None else None,
            reason=f"insufficient labeled rows; need {min_samples}",
            generated_at=_now(),
            runtime_effect="observe_only_no_live_authority",
            dependency_status=deps,
        )

    if deps["packages"].get("sklearn", {}).get("available"):
        try:
            from sklearn.ensemble import RandomForestClassifier
            from sklearn.metrics import accuracy_score

            split = max(1, int(sample_size * 0.8))
            x_train, x_test = features[:split], features[split:]
            y_train, y_test = labels[:split], labels[split:]
            model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
            model.fit(x_train, y_train)
            predictions = model.predict(x_test) if x_test else []
            accuracy = accuracy_score(y_test, predictions) if y_test else None
            written_artifact = None
            if artifact_path:
                try:
                    import joblib

                    artifact = {
                        "version": SUPERVISED_MODEL_VERSION,
                        "provider": "sklearn_random_forest",
                        "feature_columns": feature_columns,
                        "horizon": horizon,
                        "sample_size": sample_size,
                        "baseline_positive_rate": round(sum(labels) / sample_size, 4),
                        "accuracy": round(float(accuracy), 4) if accuracy is not None else None,
                        "generated_at": _now(),
                        "runtime_effect": "observe_only_no_live_authority",
                    }
                    path = Path(artifact_path)
                    path.parent.mkdir(parents=True, exist_ok=True)
                    joblib.dump({"model": model, "metadata": artifact}, path)
                    atomic_write_json(path.with_suffix(path.suffix + ".metadata.json"), artifact)
                    written_artifact = str(path)
                except Exception:
                    written_artifact = None
            return SupervisedTrainingResult(
                version=SUPERVISED_MODEL_VERSION,
                provider="sklearn_random_forest",
                trained=True,
                sample_size=sample_size,
                feature_columns=feature_columns,
                accuracy=round(float(accuracy), 4) if accuracy is not None else None,
                baseline_positive_rate=round(sum(labels) / sample_size, 4),
                reason="trained sklearn RandomForestClassifier",
                generated_at=_now(),
                runtime_effect="observe_only_no_live_authority",
                dependency_status=deps,
                artifact_path=written_artifact,
            )
        except Exception as exc:
            provider = "sklearn_random_forest_failed"
            reason = str(exc)
    else:
        provider = "chronological_baseline"
        reason = "sklearn unavailable; using positive-rate baseline"

    split = max(1, int(sample_size * 0.8))
    train_rate = sum(labels[:split]) / len(labels[:split])
    baseline_pred = 1 if train_rate >= 0.5 else 0
    test = labels[split:]
    accuracy = (
        sum(1 for item in test if item == baseline_pred) / len(test)
        if test
        else None
    )
    return SupervisedTrainingResult(
        version=SUPERVISED_MODEL_VERSION,
        provider=provider,
        trained=True,
        sample_size=sample_size,
        feature_columns=feature_columns,
        accuracy=round(accuracy, 4) if accuracy is not None else None,
        baseline_positive_rate=round(sum(labels) / sample_size, 4),
        reason=reason,
        generated_at=_now(),
        runtime_effect="observe_only_no_live_authority",
        dependency_status=deps,
        artifact_path=None,
    )


def train_quant_model_suite(
    *,
    rows: list[dict[str, Any]],
    horizon: str = "15m",
    feature_columns: list[str] | None = None,
    min_samples: int = 40,
    artifact_dir: Path | str | None = None,
    model_id_prefix: str = "quant_suite",
) -> QuantModelSuiteResult:
    """Train optional quant models side by side for observe-only comparison."""
    feature_columns = list(feature_columns or DEFAULT_FEATURE_COLUMNS)
    features, labels = _build_labeled_matrix(
        rows,
        horizon=horizon,
        feature_columns=feature_columns,
    )
    deps = optional_dependency_status()
    sample_size = len(labels)
    positive_rate = round(sum(labels) / sample_size, 4) if sample_size else None
    notes = [
        "suite is observe-only and cannot approve, size, block, or execute trades",
        "chronological split is used; no random shuffling",
    ]
    models: list[dict[str, Any]] = []

    if sample_size < min_samples:
        return QuantModelSuiteResult(
            version=QUANT_MODEL_SUITE_VERSION,
            runtime_effect="observe_only_no_live_authority",
            horizon=horizon,
            sample_size=sample_size,
            feature_columns=feature_columns,
            models=[
                _model_row(
                    provider="baseline_insufficient_data",
                    trained=False,
                    accuracy=None,
                    baseline_positive_rate=positive_rate,
                    reason=f"insufficient labeled rows; need {min_samples}",
                )
            ],
            best_model=None,
            dependency_status=deps,
            notes=notes,
        )

    x_train, x_test, y_train, y_test = _chronological_split(features, labels)
    train_rate = sum(y_train) / len(y_train)
    baseline_pred = 1 if train_rate >= 0.5 else 0
    models.append(
        _model_row(
            provider="chronological_positive_rate_baseline",
            trained=True,
            accuracy=_accuracy(y_test, [baseline_pred] * len(y_test)),
            baseline_positive_rate=positive_rate,
            reason="baseline predicts the training-window majority class",
        )
    )

    artifact_root = Path(artifact_dir) if artifact_dir else None
    if deps["packages"].get("sklearn", {}).get("available"):
        try:
            from sklearn.ensemble import RandomForestClassifier

            model = RandomForestClassifier(n_estimators=100, max_depth=5, random_state=42)
            model.fit(x_train, y_train)
            preds = [int(value) for value in model.predict(x_test)] if x_test else []
            artifact_path = None
            if artifact_root is not None:
                import joblib

                artifact_root.mkdir(parents=True, exist_ok=True)
                path = artifact_root / f"{model_id_prefix}_random_forest.joblib"
                metadata = {
                    "version": SUPERVISED_MODEL_VERSION,
                    "suite_version": QUANT_MODEL_SUITE_VERSION,
                    "provider": "sklearn_random_forest",
                    "feature_columns": feature_columns,
                    "horizon": horizon,
                    "sample_size": sample_size,
                    "generated_at": _now(),
                    "runtime_effect": "observe_only_no_live_authority",
                }
                joblib.dump({"model": model, "metadata": metadata}, path)
                atomic_write_json(path.with_suffix(path.suffix + ".metadata.json"), metadata)
                artifact_path = str(path)
            models.append(
                _model_row(
                    provider="sklearn_random_forest",
                    trained=True,
                    accuracy=_accuracy(y_test, preds),
                    baseline_positive_rate=positive_rate,
                    reason="trained sklearn RandomForestClassifier",
                    artifact_path=artifact_path,
                )
            )
        except Exception as exc:
            models.append(
                _model_row(
                    provider="sklearn_random_forest",
                    trained=False,
                    accuracy=None,
                    baseline_positive_rate=positive_rate,
                    reason=f"sklearn training failed: {exc}",
                )
            )

    if deps["packages"].get("xgboost", {}).get("available"):
        try:
            from xgboost import XGBClassifier

            model = XGBClassifier(
                n_estimators=50,
                max_depth=3,
                learning_rate=0.08,
                subsample=0.9,
                colsample_bytree=0.9,
                eval_metric="logloss",
                random_state=42,
            )
            model.fit(x_train, y_train)
            preds = [int(value) for value in model.predict(x_test)] if x_test else []
            artifact_path = None
            if artifact_root is not None:
                import joblib

                artifact_root.mkdir(parents=True, exist_ok=True)
                path = artifact_root / f"{model_id_prefix}_xgboost.joblib"
                metadata = {
                    "version": SUPERVISED_MODEL_VERSION,
                    "suite_version": QUANT_MODEL_SUITE_VERSION,
                    "provider": "xgboost_classifier",
                    "feature_columns": feature_columns,
                    "horizon": horizon,
                    "sample_size": sample_size,
                    "generated_at": _now(),
                    "runtime_effect": "observe_only_no_live_authority",
                }
                joblib.dump({"model": model, "metadata": metadata}, path)
                atomic_write_json(path.with_suffix(path.suffix + ".metadata.json"), metadata)
                artifact_path = str(path)
            models.append(
                _model_row(
                    provider="xgboost_classifier",
                    trained=True,
                    accuracy=_accuracy(y_test, preds),
                    baseline_positive_rate=positive_rate,
                    reason="trained XGBClassifier",
                    artifact_path=artifact_path,
                )
            )
        except Exception as exc:
            models.append(
                _model_row(
                    provider="xgboost_classifier",
                    trained=False,
                    accuracy=None,
                    baseline_positive_rate=positive_rate,
                    reason=f"xgboost training failed: {exc}",
                )
            )

    best = None
    trained = [row for row in models if row.get("trained") and row.get("accuracy") is not None]
    if trained:
        best = sorted(
            trained,
            key=lambda row: (float(row.get("accuracy") or 0.0), row.get("provider") or ""),
            reverse=True,
        )[0]

    return QuantModelSuiteResult(
        version=QUANT_MODEL_SUITE_VERSION,
        runtime_effect="observe_only_no_live_authority",
        horizon=horizon,
        sample_size=sample_size,
        feature_columns=feature_columns,
        models=models,
        best_model=best,
        dependency_status=deps,
        notes=notes,
    )
