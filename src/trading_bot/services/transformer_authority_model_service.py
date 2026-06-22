"""Torch Transformer training, inference, and governed authority adapter."""

from __future__ import annotations

import os
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from services.supervised_prediction_training_service import (
    DEFAULT_FEATURE_COLUMNS,
    _build_labeled_matrix,
    _float,
)

from ml_platform.config import MODEL_REGISTRY_PATH
from ml_platform.registry import load_registry, model_staleness_guard

TRANSFORMER_AUTHORITY_VERSION = "transformer_authority_v1"
TRANSFORMER_RUNTIME_EFFECT = "governed_model_authority_adapter"
TRANSFORMER_LIVE_STATUSES = {"warn_only", "paper_soft", "paper_gate", "live_candidate"}


@dataclass(frozen=True)
class TransformerTrainingResult:
    version: str
    provider: str
    trained: bool
    sample_size: int
    feature_columns: list[str]
    accuracy: float | None
    reason: str
    generated_at: str
    runtime_effect: str
    artifact_path: str | None
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _load_torch():
    import torch
    from torch import nn

    return torch, nn


def _safe_sigmoid(value: float) -> float:
    import math

    if value >= 0:
        z = math.exp(-value)
        return 1.0 / (1.0 + z)
    z = math.exp(value)
    return z / (1.0 + z)


def _risk_probability_from_forecast(
    account_state: dict[str, Any],
) -> tuple[float | None, str | None]:
    containers = [
        account_state.get("tft_multi_horizon_forecast"),
        account_state.get("multi_horizon_forecast"),
        account_state.get("transformer_forecast"),
        account_state.get("transformer_authority_forecast"),
    ]
    keys = (
        "high_risk_excursion_probability",
        "risk_excursion_probability",
        "downside_excursion_probability",
        "probability_high_risk_excursion",
        "t60_high_risk_probability",
        "t60_liquidity_cliff_probability",
    )
    for container in containers:
        if not isinstance(container, dict):
            continue
        for key in keys:
            try:
                if container.get(key) is not None:
                    return float(container.get(key)), key
            except Exception:
                continue
    return None, None


def _model_by_id(registry: dict[str, Any], model_id: str) -> dict[str, Any] | None:
    for model in registry.get("models") or []:
        if str(model.get("model_id") or "") == model_id:
            return model
    return None


def _make_transformer_model(torch, nn, *, input_dim: int, hidden_dim: int = 32):
    class TinyTabularTransformer(nn.Module):
        def __init__(self):
            super().__init__()
            self.input_proj = nn.Linear(input_dim, hidden_dim)
            encoder_layer = nn.TransformerEncoderLayer(
                d_model=hidden_dim,
                nhead=4,
                dim_feedforward=hidden_dim * 2,
                dropout=0.0,
                batch_first=True,
            )
            self.encoder = nn.TransformerEncoder(encoder_layer, num_layers=1)
            self.head = nn.Linear(hidden_dim, 1)

        def forward(self, x):
            projected = self.input_proj(x.unsqueeze(1))
            encoded = self.encoder(projected)
            return self.head(encoded[:, -1, :]).squeeze(-1)

    return TinyTabularTransformer()


def train_transformer_authority_model(
    *,
    rows: list[dict[str, Any]],
    horizon: str = "triple_barrier",
    feature_columns: list[str] | None = None,
    min_samples: int = 500,
    artifact_path: Path | str | None = None,
    epochs: int = 8,
    learning_rate: float = 0.003,
) -> TransformerTrainingResult:
    feature_columns = list(feature_columns or DEFAULT_FEATURE_COLUMNS)
    features, labels, _row_timestamps = _build_labeled_matrix(
        rows,
        horizon=horizon,
        feature_columns=feature_columns,
    )
    sample_size = len(labels)
    if sample_size < min_samples:
        return TransformerTrainingResult(
            version=TRANSFORMER_AUTHORITY_VERSION,
            provider="torch_transformer",
            trained=False,
            sample_size=sample_size,
            feature_columns=feature_columns,
            accuracy=None,
            reason=f"insufficient labeled rows; need {min_samples}",
            generated_at=_now(),
            runtime_effect="candidate_training_only_no_live_authority",
            artifact_path=None,
            metadata={},
        )
    try:
        torch, nn = _load_torch()
    except Exception as exc:
        return TransformerTrainingResult(
            version=TRANSFORMER_AUTHORITY_VERSION,
            provider="torch_transformer_unavailable",
            trained=False,
            sample_size=sample_size,
            feature_columns=feature_columns,
            accuracy=None,
            reason=f"torch unavailable: {exc}",
            generated_at=_now(),
            runtime_effect="candidate_training_only_no_live_authority",
            artifact_path=None,
            metadata={},
        )

    split = max(1, int(sample_size * 0.8))
    x_train = torch.tensor(features[:split], dtype=torch.float32)
    y_train = torch.tensor(
        [1.0 if value > 0 else 0.0 for value in labels[:split]], dtype=torch.float32
    )
    x_test = torch.tensor(features[split:], dtype=torch.float32)
    y_test = torch.tensor(
        [1.0 if value > 0 else 0.0 for value in labels[split:]], dtype=torch.float32
    )

    torch.manual_seed(42)
    model = _make_transformer_model(torch, nn, input_dim=len(feature_columns))
    optimizer = torch.optim.Adam(model.parameters(), lr=float(learning_rate))
    criterion = nn.BCEWithLogitsLoss()
    model.train()
    for _ in range(max(1, int(epochs))):
        optimizer.zero_grad()
        loss = criterion(model(x_train), y_train)
        loss.backward()
        optimizer.step()

    model.eval()
    accuracy = None
    if len(y_test) > 0:
        with torch.no_grad():
            probs = torch.sigmoid(model(x_test))
            preds = (probs >= 0.5).float()
            accuracy = float((preds == y_test).float().mean().item())
    metadata = {
        "version": TRANSFORMER_AUTHORITY_VERSION,
        "provider": "torch_transformer",
        "feature_columns": feature_columns,
        "horizon": horizon,
        "sample_size": sample_size,
        "hidden_dim": 32,
        "epochs": max(1, int(epochs)),
        "learning_rate": float(learning_rate),
        "accuracy": round(accuracy, 4) if accuracy is not None else None,
        "generated_at": _now(),
        "runtime_effect": "candidate_artifact_no_live_authority",
        "authority_contract": "requires_registry_status_env_and_staleness_guard",
    }
    written_path = None
    if artifact_path is not None:
        path = Path(artifact_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        torch.save({"state_dict": model.state_dict(), "metadata": metadata}, path)
        written_path = str(path)
    return TransformerTrainingResult(
        version=TRANSFORMER_AUTHORITY_VERSION,
        provider="torch_transformer",
        trained=True,
        sample_size=sample_size,
        feature_columns=feature_columns,
        accuracy=round(accuracy, 4) if accuracy is not None else None,
        reason="trained torch Transformer encoder candidate",
        generated_at=metadata["generated_at"],
        runtime_effect="candidate_training_only_no_live_authority",
        artifact_path=written_path,
        metadata=metadata,
    )


def score_transformer_authority_artifact(
    *,
    artifact_path: Path | str,
    features: dict[str, Any],
) -> dict[str, Any]:
    try:
        torch, nn = _load_torch()
    except Exception as exc:
        return {"scored": False, "reason": f"torch unavailable: {exc}"}
    try:
        payload = torch.load(Path(artifact_path), map_location="cpu")
        metadata = dict(payload.get("metadata") or {})
        feature_columns = list(metadata.get("feature_columns") or DEFAULT_FEATURE_COLUMNS)
        model = _make_transformer_model(
            torch,
            nn,
            input_dim=len(feature_columns),
            hidden_dim=int(metadata.get("hidden_dim") or 32),
        )
        model.load_state_dict(payload["state_dict"])
        model.eval()
        vector = torch.tensor(
            [[_float(features.get(col)) for col in feature_columns]], dtype=torch.float32
        )
        with torch.no_grad():
            raw = float(model(vector).item())
        probability = _safe_sigmoid(raw)
        return {
            "scored": True,
            "provider": metadata.get("provider") or "torch_transformer",
            "model_version": metadata.get("version") or TRANSFORMER_AUTHORITY_VERSION,
            "probability": round(probability, 6),
            "score": round(probability * 100.0, 4),
            "feature_count": len(feature_columns),
            "runtime_effect": "model_score_only",
        }
    except Exception as exc:
        return {"scored": False, "reason": f"transformer scoring failed: {exc}"}


def evaluate_transformer_authority(
    *,
    symbol: str,
    action: str,
    account_state: dict[str, Any] | None = None,
    env: dict[str, str] | None = None,
    registry_path: Path | str = MODEL_REGISTRY_PATH,
) -> dict[str, Any]:
    """Return a governed Transformer authority signal.

    This is a decision-policy input. It never submits orders and cannot increase
    size. Authority requires explicit env enablement, a configured model id,
    allowed registry status, and a fresh artifact.
    """
    account_state = account_state if isinstance(account_state, dict) else {}
    env = dict(os.environ if env is None else env)
    enabled = str(env.get("TRANSFORMER_AUTHORITY_ENABLED", "false")).lower() in {
        "1",
        "true",
        "yes",
        "on",
    }
    mode = str(env.get("TRANSFORMER_AUTHORITY_MODE", "observe_only")).lower()
    model_id = str(env.get("TRANSFORMER_MODEL_ID") or env.get("ML_MODEL_ID") or "").strip()
    max_age = int(
        env.get("TRANSFORMER_MODEL_MAX_AGE_SECONDS") or env.get("ML_MODEL_MAX_AGE_SECONDS") or 0
    )
    base = {
        "version": TRANSFORMER_AUTHORITY_VERSION,
        "runtime_effect": TRANSFORMER_RUNTIME_EFFECT,
        "symbol": symbol.upper(),
        "action": action.lower(),
        "enabled": enabled,
        "mode": mode,
        "model_id": model_id,
        "decision": "no_authority",
        "size_multiplier": 1.0,
        "can_increase_size": False,
        "can_submit_orders": False,
    }
    if not enabled or not model_id:
        return {**base, "reason": "transformer authority not enabled or model id missing"}
    registry = load_registry(registry_path)
    model = _model_by_id(registry, model_id)
    status = str((model or {}).get("status") or "").lower()
    if status not in TRANSFORMER_LIVE_STATUSES:
        return {
            **base,
            "status": status,
            "reason": "registry status does not grant transformer authority",
        }
    guard = model_staleness_guard(
        model_id=model_id,
        max_age_seconds=max_age,
        registry_path=registry_path,
    )
    if guard.get("fallback_required"):
        return {
            **base,
            "status": status,
            "staleness_guard": guard,
            "reason": "model staleness guard requires fallback",
        }
    features = (
        account_state.get("bar_pattern_features")
        or account_state.get("latest_bar_pattern_features")
        or account_state.get("historical_bar_features")
        or {}
    )
    score = score_transformer_authority_artifact(
        artifact_path=str((model or {}).get("artifact_path") or ""),
        features=features if isinstance(features, dict) else {},
    )
    if not score.get("scored"):
        return {
            **base,
            "status": status,
            "staleness_guard": guard,
            "score": score,
            "reason": score.get("reason"),
        }
    probability = float(score.get("probability") or 0.0)
    block_threshold = float(env.get("TRANSFORMER_BLOCK_THRESHOLD", "0.35"))
    size_down_threshold = float(env.get("TRANSFORMER_SIZE_DOWN_THRESHOLD", "0.45"))
    support_threshold = float(env.get("TRANSFORMER_SUPPORT_THRESHOLD", "0.60"))
    risk_excursion_threshold = float(env.get("TRANSFORMER_HIGH_RISK_EXCURSION_THRESHOLD", "0.70"))
    risk_probability, risk_probability_source = _risk_probability_from_forecast(account_state)
    decision = "allow"
    size_multiplier = 1.0
    reason = "transformer authority allows"
    if (
        risk_probability is not None
        and risk_probability >= risk_excursion_threshold
        and mode in {"paper_gate", "live_candidate", "warn_only"}
    ):
        decision = "block"
        size_multiplier = 0.0
        reason = (
            "transformer high-risk excursion forecast "
            f"{risk_probability:.3f} >= threshold {risk_excursion_threshold:.3f}"
        )
    elif probability < block_threshold and mode in {"paper_gate", "live_candidate", "warn_only"}:
        decision = "block"
        size_multiplier = 0.0
        reason = (
            f"transformer probability {probability:.3f} below block threshold {block_threshold:.3f}"
        )
    elif probability < size_down_threshold and mode in {
        "paper_soft",
        "paper_gate",
        "live_candidate",
        "warn_only",
    }:
        decision = "size_down"
        size_multiplier = 0.65
        reason = f"transformer probability {probability:.3f} below size-down threshold {size_down_threshold:.3f}"
    elif probability >= support_threshold:
        reason = f"transformer probability {probability:.3f} supports candidate"
    return {
        **base,
        "status": status,
        "decision": decision,
        "size_multiplier": size_multiplier,
        "reason": reason,
        "probability": round(probability, 6),
        "risk_excursion_probability": (
            round(risk_probability, 6) if risk_probability is not None else None
        ),
        "risk_excursion_probability_source": risk_probability_source,
        "risk_excursion_threshold": risk_excursion_threshold,
        "score": score,
        "staleness_guard": guard,
    }
