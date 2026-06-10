"""Supervised ML prediction training scaffold over feature snapshots.

This service uses optional sklearn when available and a deterministic baseline
otherwise. It is observe-only and never writes orders or changes live authority.
"""

from __future__ import annotations

import math
from collections import Counter
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from policy_artifacts import atomic_write_json
from repositories.supervised_prediction_training_repo import (
    fetch_training_rows as repo_fetch_training_rows,
)
from services.optional_dependency_service import optional_dependency_status

from ml_platform.lifecycle import REQUIRED_PROMOTION_METRICS

SUPERVISED_MODEL_VERSION = "supervised_prediction_model_v2"
QUANT_MODEL_SUITE_VERSION = "quant_model_suite_v3"
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
    "sma_20",
    "bollinger_upper_20",
    "bollinger_lower_20",
    "bollinger_width_20_pct",
    "bollinger_percent_b_20",
    "rolling_volatility_20_pct",
    "day_of_week",
    "minute_of_day",
    "ema_12",
    "ema_26",
    "macd",
    "macd_signal",
    "rsi_14",
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
ADVANCED_ALPHA_FEATURE_COLUMNS = (
    "volume_delta",
    "institutional_volume_delta",
    "cumulative_volume_delta",
    "cvd_price_corr_20",
    "vpin_toxicity_20",
    "fractional_diff_close_045",
    "fractional_diff_zscore_20",
)
EXECUTION_MICROSTRUCTURE_FEATURE_COLUMNS = (
    "bid_ask_spread_pct",
    "slippage_estimate_pct",
    "execution_cost_estimate_pct",
    "liquidity_sweep_risk",
)
DEFAULT_FEATURE_COLUMNS = (
    DEFAULT_FEATURE_COLUMNS
    + CANDLE_PHYSICS_FEATURE_COLUMNS
    + ADVANCED_ALPHA_FEATURE_COLUMNS
    + EXECUTION_MICROSTRUCTURE_FEATURE_COLUMNS
)
TRIPLE_BARRIER_TARGETS = ("triple_barrier", "triple_barrier_label")
TREND_SCAN_TARGETS = ("trend_scan", "trend_scan_label")
ASYMMETRIC_XGBOOST_FALSE_POSITIVE_PENALTY = 10.0


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
    validation_method: str = "chronological_80_20_observe_only"
    promotion_eligible: bool = False
    promotion_metrics: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        return data


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
    if horizon in TREND_SCAN_TARGETS:
        try:
            value = row.get("trend_scan_label")
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


def _safe_div(numerator: float, denominator: float) -> float | None:
    if denominator == 0:
        return None
    return numerator / denominator


def _promotion_metric_shell(
    y_true: list[int],
    y_pred: list[int],
    *,
    probabilities: list[float] | None = None,
) -> dict[str, Any]:
    """Return trading-relevant metrics, even when some require later reports.

    The training scaffold can compute classification/calibration basics. Metrics
    that require replay, fills, MFE/MAE, slippage, or regime grouping are
    intentionally left as None so promotion governance cannot confuse a trained
    scaffold with complete lifecycle evidence.
    """
    actual = [1 if int(value) > 0 else 0 for value in y_true]
    pred = [1 if int(value) > 0 else 0 for value in y_pred]
    tp = sum(1 for a, p in zip(actual, pred) if a == 1 and p == 1)
    tn = sum(1 for a, p in zip(actual, pred) if a == 0 and p == 0)
    fp = sum(1 for a, p in zip(actual, pred) if a == 0 and p == 1)
    fn = sum(1 for a, p in zip(actual, pred) if a == 1 and p == 0)
    probabilities = probabilities or [float(value) for value in pred]
    brier = None
    if actual and len(probabilities) == len(actual):
        brier = sum((prob - a) ** 2 for prob, a in zip(probabilities, actual)) / len(actual)
    expected_value = None
    if actual:
        # Simple proxy: correct approvals/rejections +1, false positives -2,
        # false negatives -1. Real EV must come from replay/fill reports.
        expected_value = (tp + tn - (2 * fp) - fn) / len(actual)
    metrics = {
        "expected_value_per_decision": round(expected_value, 6)
        if expected_value is not None
        else None,
        "false_positive_cost": fp,
        "false_negative_opportunity_cost": fn,
        "avoid_loser_precision": round(_safe_div(tn, tn + fn), 6)
        if _safe_div(tn, tn + fn) is not None
        else None,
        "avoid_loser_recall": round(_safe_div(tn, tn + fp), 6)
        if _safe_div(tn, tn + fp) is not None
        else None,
        "brier_score": round(brier, 6) if brier is not None else None,
        "calibration_error": None,
        "profit_factor": None,
        "max_drawdown_impact": None,
        "average_mfe_delta": None,
        "average_mae_delta": None,
        "slippage_adjusted_decision_delta": None,
        "capture_ratio_improvement": None,
        "regime_specific_performance": None,
        "symbol_specific_stability": None,
        "time_of_day_stability": None,
    }
    for key in REQUIRED_PROMOTION_METRICS:
        metrics.setdefault(key, None)
    return metrics


def _positive_rate(labels: list[int]) -> float | None:
    if not labels:
        return None
    return round(sum(1 for value in labels if value > 0) / len(labels), 4)


def _majority_label(labels: list[int]) -> int:
    return Counter(labels).most_common(1)[0][0]


def _binary_labels(labels: list[int]) -> list[int]:
    return [1 if int(value) > 0 else 0 for value in labels]


def _sigmoid(value: float) -> float:
    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def asymmetric_false_positive_logistic_objective(
    preds: Any,
    dtrain: Any,
    *,
    false_positive_penalty: float = ASYMMETRIC_XGBOOST_FALSE_POSITIVE_PENALTY,
) -> tuple[Any, Any]:
    """XGBoost custom objective that penalizes false-positive pressure harder.

    Labels are binary: 1 means the forward label supports a trade, 0 means it
    does not. When the model assigns high probability to a 0 label, the gradient
    and Hessian are scaled up so stop-out-prone false positives cost more than
    missed positives. This remains observe-only until promotion governance says
    otherwise.
    """
    labels = dtrain.get_label()
    penalty = max(1.0, float(false_positive_penalty or 1.0))
    grad = []
    hess = []
    for raw_pred, label in zip(preds, labels):
        prob = _sigmoid(float(raw_pred))
        y = 1.0 if float(label) > 0.0 else 0.0
        weight = penalty if y < prob else 1.0
        grad.append((prob - y) * weight)
        hess.append(max(prob * (1.0 - prob) * weight, 1e-6))
    return grad, hess


def _model_row(
    *,
    provider: str,
    trained: bool,
    accuracy: float | None,
    reason: str,
    artifact_path: str | None = None,
    baseline_positive_rate: float | None = None,
    validation_method: str = "chronological_80_20_observe_only",
    promotion_metrics: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "provider": provider,
        "trained": trained,
        "accuracy": accuracy,
        "baseline_positive_rate": baseline_positive_rate,
        "reason": reason,
        "artifact_path": artifact_path,
        "runtime_effect": "observe_only_no_live_authority",
        "validation_method": validation_method,
        "promotion_eligible": False,
        "promotion_metrics": promotion_metrics or {},
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
        positive_rate = _positive_rate(labels)
        return SupervisedTrainingResult(
            version=SUPERVISED_MODEL_VERSION,
            provider="baseline_insufficient_data",
            trained=False,
            sample_size=sample_size,
            feature_columns=feature_columns,
            accuracy=None,
            baseline_positive_rate=positive_rate,
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
            promotion_metrics = (
                _promotion_metric_shell(
                    y_test,
                    [int(value) for value in predictions],
                )
                if y_test
                else {}
            )
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
                        "baseline_positive_rate": _positive_rate(labels),
                        "accuracy": round(float(accuracy), 4) if accuracy is not None else None,
                        "validation_method": "chronological_80_20_observe_only",
                        "promotion_eligible": False,
                        "promotion_metrics": promotion_metrics,
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
                baseline_positive_rate=_positive_rate(labels),
                reason="trained sklearn RandomForestClassifier",
                generated_at=_now(),
                runtime_effect="observe_only_no_live_authority",
                dependency_status=deps,
                artifact_path=written_artifact,
                validation_method="chronological_80_20_observe_only",
                promotion_eligible=False,
                promotion_metrics=promotion_metrics,
            )
        except Exception as exc:
            provider = "sklearn_random_forest_failed"
            reason = str(exc)
    else:
        provider = "chronological_baseline"
        reason = "sklearn unavailable; using positive-rate baseline"

    split = max(1, int(sample_size * 0.8))
    baseline_pred = _majority_label(labels[:split])
    test = labels[split:]
    accuracy = sum(1 for item in test if item == baseline_pred) / len(test) if test else None
    baseline_preds = [baseline_pred] * len(test)
    return SupervisedTrainingResult(
        version=SUPERVISED_MODEL_VERSION,
        provider=provider,
        trained=True,
        sample_size=sample_size,
        feature_columns=feature_columns,
        accuracy=round(accuracy, 4) if accuracy is not None else None,
        baseline_positive_rate=_positive_rate(labels),
        reason=reason,
        generated_at=_now(),
        runtime_effect="observe_only_no_live_authority",
        dependency_status=deps,
        artifact_path=None,
        validation_method="chronological_80_20_observe_only",
        promotion_eligible=False,
        promotion_metrics=_promotion_metric_shell(test, baseline_preds) if test else {},
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
    positive_rate = _positive_rate(labels)
    notes = [
        "suite is observe-only and cannot approve, size, block, or execute trades",
        "chronological split is used for scaffold comparison only; promotion requires purged walk-forward validation",
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
    baseline_pred = _majority_label(y_train)
    models.append(
        _model_row(
            provider="chronological_positive_rate_baseline",
            trained=True,
            accuracy=_accuracy(y_test, [baseline_pred] * len(y_test)),
            baseline_positive_rate=positive_rate,
            reason="baseline predicts the training-window majority class",
            promotion_metrics=_promotion_metric_shell(y_test, [baseline_pred] * len(y_test)),
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
                    promotion_metrics=_promotion_metric_shell(y_test, preds),
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
            class_values = sorted(set(y_train + y_test))
            label_to_index = {value: idx for idx, value in enumerate(class_values)}
            index_to_label = {idx: value for value, idx in label_to_index.items()}
            y_train_encoded = [label_to_index[value] for value in y_train]
            model.fit(x_train, y_train_encoded)
            raw_preds = [int(value) for value in model.predict(x_test)] if x_test else []
            preds = [index_to_label.get(value, value) for value in raw_preds]
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
                    promotion_metrics=_promotion_metric_shell(y_test, preds),
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
        try:
            import xgboost as xgb

            y_train_binary = _binary_labels(y_train)
            y_test_binary = _binary_labels(y_test)
            dtrain = xgb.DMatrix(x_train, label=y_train_binary, feature_names=feature_columns)
            dtest = xgb.DMatrix(x_test, label=y_test_binary, feature_names=feature_columns)
            params = {
                "max_depth": 3,
                "eta": 0.08,
                "subsample": 0.9,
                "colsample_bytree": 0.9,
                "eval_metric": "logloss",
                "seed": 42,
            }
            model = xgb.train(
                params,
                dtrain,
                num_boost_round=50,
                obj=asymmetric_false_positive_logistic_objective,
                verbose_eval=False,
            )
            raw_probs = [float(value) for value in model.predict(dtest)] if x_test else []
            preds = [1 if _sigmoid(value) >= 0.5 else 0 for value in raw_probs]
            artifact_path = None
            if artifact_root is not None:
                import joblib

                artifact_root.mkdir(parents=True, exist_ok=True)
                path = artifact_root / f"{model_id_prefix}_xgboost_asymmetric.joblib"
                metadata = {
                    "version": SUPERVISED_MODEL_VERSION,
                    "suite_version": QUANT_MODEL_SUITE_VERSION,
                    "provider": "xgboost_asymmetric_false_positive",
                    "objective": "custom_asymmetric_false_positive_logistic",
                    "false_positive_penalty": ASYMMETRIC_XGBOOST_FALSE_POSITIVE_PENALTY,
                    "feature_columns": feature_columns,
                    "horizon": horizon,
                    "sample_size": sample_size,
                    "generated_at": _now(),
                    "runtime_effect": "observe_only_no_live_authority",
                    "validation_method": "chronological_80_20_observe_only",
                    "promotion_eligible": False,
                }
                joblib.dump({"model": model, "metadata": metadata}, path)
                atomic_write_json(path.with_suffix(path.suffix + ".metadata.json"), metadata)
                artifact_path = str(path)
            models.append(
                _model_row(
                    provider="xgboost_asymmetric_false_positive",
                    trained=True,
                    accuracy=_accuracy(y_test_binary, preds),
                    baseline_positive_rate=_positive_rate(y_test_binary),
                    reason=(
                        "trained xgboost custom objective with "
                        f"{ASYMMETRIC_XGBOOST_FALSE_POSITIVE_PENALTY:g}x false-positive penalty"
                    ),
                    artifact_path=artifact_path,
                    promotion_metrics=_promotion_metric_shell(y_test_binary, preds),
                )
            )
        except Exception as exc:
            models.append(
                _model_row(
                    provider="xgboost_asymmetric_false_positive",
                    trained=False,
                    accuracy=None,
                    baseline_positive_rate=positive_rate,
                    reason=f"asymmetric xgboost training failed: {exc}",
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
