"""Supervised ML prediction training scaffold over feature snapshots.

This service uses optional sklearn when available and a deterministic baseline
otherwise. It is observe-only and never writes orders or changes live authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
import sqlite3
from typing import Any

from db import DB_PATH
from services.optional_dependency_service import optional_dependency_status
from policy_artifacts import atomic_write_json


SUPERVISED_MODEL_VERSION = "supervised_prediction_model_v1"
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
    col = f"ret_fwd_{horizon}"
    try:
        value = row.get(col)
        if value is None:
            return None
        return 1 if float(value) > 0 else 0
    except Exception:
        return None


def fetch_training_rows(
    *,
    db_path: Path | str = DB_PATH,
    symbol: str | None = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    path = Path(db_path)
    if not path.exists():
        return []
    symbol_sql = ""
    params: list[Any] = []
    if symbol:
        symbol_sql = "AND fs.symbol = ?"
        params.append(symbol.upper())
    params.append(limit)
    with sqlite3.connect(f"file:{path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='feature_snapshots'"
        ).fetchone()
        labels = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='labeled_setups'"
        ).fetchone()
        if not exists or not labels:
            return []
        rows = con.execute(
            f"""
            SELECT
                fs.symbol,
                fs.timestamp,
                fs.ret_1m,
                fs.ret_5m,
                fs.ret_15m,
                fs.range_pos_15m,
                fs.distance_from_vwap,
                fs.volume_ratio_5m,
                fs.relative_strength_5m,
                fs.spread_pct,
                fs.setup_score,
                ls.ret_fwd_5m,
                ls.ret_fwd_15m,
                ls.ret_fwd_30m
            FROM feature_snapshots fs
            JOIN labeled_setups ls ON ls.snapshot_id = fs.id
            WHERE ls.ret_fwd_15m IS NOT NULL
              {symbol_sql}
            ORDER BY fs.timestamp DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def train_supervised_prediction_model(
    *,
    rows: list[dict[str, Any]],
    horizon: str = "15m",
    feature_columns: list[str] | None = None,
    min_samples: int = 40,
    artifact_path: Path | str | None = None,
) -> SupervisedTrainingResult:
    feature_columns = list(feature_columns or DEFAULT_FEATURE_COLUMNS)
    labels = []
    features = []
    for row in rows:
        label = _label(row, horizon)
        if label is None:
            continue
        labels.append(label)
        features.append(_row_features(row, feature_columns))

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
