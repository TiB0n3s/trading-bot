"""Regime detection and model-routing structures.

This is a dependency-light scaffold for the HMM/model-matrix architecture. If
hmmlearn is installed later, it can replace the deterministic classifier behind
the same output contract.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from policy_artifacts import atomic_write_json


REGIME_ROUTER_VERSION = "regime_switching_router_v1"


@dataclass(frozen=True)
class RegimeObservation:
    version: str
    regime_id: int | None
    regime_label: str
    volatility_pct: float | None
    average_return_pct: float | None
    confidence: str
    recommended_strategy: str
    model_slot: str | None
    smoothed_regime_id: int | None
    stable: bool
    runtime_effect: str
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _floats(values: list[Any] | tuple[Any, ...] | None) -> list[float]:
    out = []
    for value in values or []:
        try:
            if value is not None:
                out.append(float(value))
        except Exception:
            continue
    return out


def _returns(closes: list[float]) -> list[float]:
    out = []
    for prev, cur in zip(closes[:-1], closes[1:]):
        if prev:
            out.append((cur - prev) / prev * 100.0)
    return out


def _std(values: list[float]) -> float:
    if not values:
        return 0.0
    mean = sum(values) / len(values)
    return (sum((value - mean) ** 2 for value in values) / len(values)) ** 0.5


def _classify(avg_return: float, vol: float) -> tuple[int, str, str]:
    if vol >= 1.6 or avg_return <= -0.35:
        return 2, "high_volatility_risk", "tighten_risk_or_hedge"
    if vol <= 0.75 and avg_return >= 0.05:
        return 0, "quiet_bull", "trend_continuation"
    return 1, "choppy_range", "mean_reversion_or_reduced_size"


def _state_to_canonical_regime_map(means: Any) -> dict[str, int]:
    """Map arbitrary HMM state IDs into canonical regime IDs.

    HMM component labels are arbitrary. The canonical mapping uses both return
    and volatility so the high-risk slot is not determined by return alone.
    Regime 2 receives the highest risk score, regime 0 receives the strongest
    return among the remaining states, and regime 1 receives the leftover state.
    """
    rows = [(idx, float(row[0]), float(row[1])) for idx, row in enumerate(means)]
    if len(rows) != 3:
        sorted_states = sorted(rows, key=lambda item: item[1], reverse=True)
        return {str(hmm_state): canonical for canonical, (hmm_state, _, _) in enumerate(sorted_states)}

    returns = [row[1] for row in rows]
    vols = [row[2] for row in rows]
    ret_mean = sum(returns) / len(returns)
    vol_mean = sum(vols) / len(vols)
    ret_std = _std(returns) or 1.0
    vol_std = _std(vols) or 1.0

    def _risk_score(item: tuple[int, float, float]) -> float:
        _, avg_ret, avg_vol = item
        return ((avg_vol - vol_mean) / vol_std) - ((avg_ret - ret_mean) / ret_std)

    high_risk_state = max(rows, key=_risk_score)[0]
    remaining = [row for row in rows if row[0] != high_risk_state]
    quiet_bull_state = max(remaining, key=lambda item: item[1])[0]
    choppy_state = next(row[0] for row in remaining if row[0] != quiet_bull_state)

    return {
        str(quiet_bull_state): 0,
        str(choppy_state): 1,
        str(high_risk_state): 2,
    }


def _smoothed(regime_history: list[int], required_hits: int, window: int) -> tuple[int | None, bool]:
    if not regime_history:
        return None, False
    recent = regime_history[-window:]
    candidate = recent[-1]
    hits = sum(1 for item in recent if item == candidate)
    return candidate, hits >= required_hits


def detect_regime(
    *,
    closes: list[Any] | tuple[Any, ...],
    regime_history: list[int] | None = None,
    smoothing_window: int = 5,
    required_hits: int = 4,
) -> RegimeObservation:
    """Classify the current regime from recent closes and smoothing history."""
    values = _floats(closes)
    reasons: list[str] = []
    if len(values) < 12:
        return RegimeObservation(
            version=REGIME_ROUTER_VERSION,
            regime_id=None,
            regime_label="insufficient_data",
            volatility_pct=None,
            average_return_pct=None,
            confidence="none",
            recommended_strategy="stand_down",
            model_slot=None,
            smoothed_regime_id=None,
            stable=False,
            runtime_effect="observe_only_no_order_authority",
            reasons=["need at least 12 closes for regime detection"],
        )

    rets = _returns(values[-30:])
    avg = sum(rets) / len(rets)
    vol = _std(rets)
    regime_id, label, strategy = _classify(avg, vol)
    history = list(regime_history or []) + [regime_id]
    smoothed_id, stable = _smoothed(history, required_hits=required_hits, window=smoothing_window)
    reasons.append(f"avg_return_pct={avg:.4f}")
    reasons.append(f"volatility_pct={vol:.4f}")
    reasons.append(f"smoothing={required_hits}_of_{smoothing_window}")

    return RegimeObservation(
        version=REGIME_ROUTER_VERSION,
        regime_id=regime_id,
        regime_label=label,
        volatility_pct=round(vol, 6),
        average_return_pct=round(avg, 6),
        confidence="medium" if stable else "low",
        recommended_strategy=strategy,
        model_slot=f"regime_{regime_id}_model",
        smoothed_regime_id=smoothed_id if stable else None,
        stable=stable,
        runtime_effect="observe_only_no_order_authority",
        reasons=reasons,
    )


def model_routing_matrix(n_regimes: int = 3) -> dict[str, Any]:
    return {
        "version": REGIME_ROUTER_VERSION,
        "runtime_effect": "model_selection_contract_only",
        "retraining_cadence": "weekly_review_not_per_tick",
        "regimes": {
            "0": {
                "label": "quiet_bull",
                "model_slot": "regime_0_model",
                "preferred_strategy": "trend_continuation",
            },
            "1": {
                "label": "choppy_range",
                "model_slot": "regime_1_model",
                "preferred_strategy": "mean_reversion_or_reduced_size",
            },
            "2": {
                "label": "high_volatility_risk",
                "model_slot": "regime_2_model",
                "preferred_strategy": "tighten_risk_or_hedge",
            },
        },
        "configured_regime_count": n_regimes,
        "guardrails": {
            "minimum_samples_per_regime": 20,
            "smoothing_required": True,
            "no_live_retraining": True,
        },
    }


def train_hmm_regime_model(
    *,
    closes: list[Any] | tuple[Any, ...],
    artifact_path: Path | str | None = None,
    n_regimes: int = 3,
) -> dict[str, Any]:
    """Train an optional hmmlearn GaussianHMM regime model and persist it."""
    values = _floats(closes)
    if len(values) < 40:
        return {
            "version": REGIME_ROUTER_VERSION,
            "trained": False,
            "provider": "hmmlearn_gaussian_hmm",
            "sample_size": len(values),
            "reason": "insufficient closes; need at least 40",
            "runtime_effect": "observe_only_no_order_authority",
            "artifact_path": None,
        }
    try:
        import joblib
        import numpy as np
        from hmmlearn.hmm import GaussianHMM
    except Exception as exc:
        return {
            "version": REGIME_ROUTER_VERSION,
            "trained": False,
            "provider": "hmmlearn_unavailable",
            "sample_size": len(values),
            "reason": str(exc),
            "runtime_effect": "observe_only_no_order_authority",
            "artifact_path": None,
        }

    returns = np.array(_returns(values), dtype=float)
    vol = []
    for idx in range(len(returns)):
        window = returns[max(0, idx - 9) : idx + 1]
        vol.append(float(np.std(window)))
    features = np.column_stack([returns, np.array(vol, dtype=float)])
    model = GaussianHMM(
        n_components=n_regimes,
        covariance_type="diag",
        n_iter=1000,
        random_state=42,
    )
    model.fit(features)
    regimes = model.predict(features)
    counts = {str(i): int((regimes == i).sum()) for i in range(n_regimes)}

    means = model.means_  # shape: (n_regimes, 2)  [avg_return, avg_vol]
    state_to_regime = _state_to_canonical_regime_map(means)

    metadata = {
        "version": REGIME_ROUTER_VERSION,
        "trained": True,
        "provider": "hmmlearn_gaussian_hmm",
        "sample_size": len(values),
        "feature_columns": ["return_pct", "rolling_volatility_pct"],
        "regime_counts": counts,
        "state_to_regime_map": state_to_regime,
        "state_mean_features": {
            str(idx): {
                "average_return_pct": round(float(row[0]), 6),
                "rolling_volatility_pct": round(float(row[1]), 6),
            }
            for idx, row in enumerate(means)
        },
        "state_mapping_method": "risk_score_then_return",
        "runtime_effect": "observe_only_no_order_authority",
        "artifact_path": str(artifact_path) if artifact_path else None,
    }
    if artifact_path:
        path = Path(artifact_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump({"model": model, "metadata": metadata, "state_to_regime_map": state_to_regime}, path)
        atomic_write_json(path.with_suffix(path.suffix + ".metadata.json"), metadata)
    return metadata


def infer_regime_from_artifact(
    *,
    closes: list[Any] | tuple[Any, ...],
    artifact_path: Path | str,
    regime_history: list[int] | None = None,
    smoothing_window: int = 5,
    required_hits: int = 4,
) -> RegimeObservation:
    """Classify the current regime using a persisted GaussianHMM artifact.

    Falls back to ``detect_regime`` (deterministic threshold classifier) if
    the artifact cannot be loaded or inference fails.
    """
    values = _floats(closes)
    if len(values) < 12:
        return RegimeObservation(
            version=REGIME_ROUTER_VERSION,
            regime_id=None,
            regime_label="insufficient_data",
            volatility_pct=None,
            average_return_pct=None,
            confidence="none",
            recommended_strategy="stand_down",
            model_slot=None,
            smoothed_regime_id=None,
            stable=False,
            runtime_effect="observe_only_no_order_authority",
            reasons=["need at least 12 closes for regime detection"],
        )

    try:
        import joblib
        import numpy as np
        artifact = joblib.load(Path(artifact_path))
        model = artifact["model"]
        state_map: dict[str, int] = artifact.get("state_to_regime_map") or {}
        if not state_map:
            raise ValueError("artifact missing required state_to_regime_map")
    except Exception as exc:
        fallback = detect_regime(
            closes=closes,
            regime_history=regime_history,
            smoothing_window=smoothing_window,
            required_hits=required_hits,
        )
        return RegimeObservation(
            version=fallback.version,
            regime_id=fallback.regime_id,
            regime_label=fallback.regime_label,
            volatility_pct=fallback.volatility_pct,
            average_return_pct=fallback.average_return_pct,
            confidence=fallback.confidence,
            recommended_strategy=fallback.recommended_strategy,
            model_slot=fallback.model_slot,
            smoothed_regime_id=fallback.smoothed_regime_id,
            stable=fallback.stable,
            runtime_effect=fallback.runtime_effect,
            reasons=[f"artifact_load_failed={exc}", "falling_back_to_deterministic"] + fallback.reasons,
        )

    try:
        import numpy as np
        rets = np.array(_returns(values[-30:]), dtype=float)
        rolling_vol = []
        for idx in range(len(rets)):
            window = rets[max(0, idx - 9): idx + 1]
            rolling_vol.append(float(np.std(window)))
        features = np.column_stack([rets, np.array(rolling_vol, dtype=float)])
        predicted = model.predict(features)
        hmm_state = int(predicted[-1])
        regime_id = state_map.get(str(hmm_state), hmm_state)
        avg = float(np.mean(rets))
        vol_val = float(np.std(rets))
    except Exception as exc:
        fallback = detect_regime(
            closes=closes,
            regime_history=regime_history,
            smoothing_window=smoothing_window,
            required_hits=required_hits,
        )
        return RegimeObservation(
            version=fallback.version,
            regime_id=fallback.regime_id,
            regime_label=fallback.regime_label,
            volatility_pct=fallback.volatility_pct,
            average_return_pct=fallback.average_return_pct,
            confidence=fallback.confidence,
            recommended_strategy=fallback.recommended_strategy,
            model_slot=fallback.model_slot,
            smoothed_regime_id=fallback.smoothed_regime_id,
            stable=fallback.stable,
            runtime_effect=fallback.runtime_effect,
            reasons=[f"hmm_predict_failed={exc}", "falling_back_to_deterministic"] + fallback.reasons,
        )

    label_map = {
        0: ("quiet_bull", "trend_continuation"),
        1: ("choppy_range", "mean_reversion_or_reduced_size"),
        2: ("high_volatility_risk", "tighten_risk_or_hedge"),
    }
    label, strategy = label_map.get(regime_id, ("unknown", "stand_down"))
    history = list(regime_history or []) + [regime_id]
    smoothed_id, stable = _smoothed(history, required_hits=required_hits, window=smoothing_window)

    return RegimeObservation(
        version=REGIME_ROUTER_VERSION,
        regime_id=regime_id,
        regime_label=label,
        volatility_pct=round(vol_val, 6),
        average_return_pct=round(avg, 6),
        confidence="medium" if stable else "low",
        recommended_strategy=strategy,
        model_slot=f"regime_{regime_id}_model",
        smoothed_regime_id=smoothed_id if stable else None,
        stable=stable,
        runtime_effect="observe_only_no_order_authority",
        reasons=[
            f"hmm_state={hmm_state}",
            f"canonical_regime={regime_id}",
            f"avg_return_pct={avg:.4f}",
            f"volatility_pct={vol_val:.4f}",
            f"provider=hmmlearn_gaussian_hmm",
            f"smoothing={required_hits}_of_{smoothing_window}",
        ],
    )


def load_regime_state(state_path: Path | str) -> dict[str, Any]:
    """Load persisted regime history from a JSON file."""
    path = Path(state_path)
    if not path.exists():
        return {"history": [], "last_updated": None}
    try:
        data = json.loads(path.read_text())
        return data if isinstance(data, dict) else {"history": [], "last_updated": None}
    except Exception:
        return {"history": [], "last_updated": None}


def save_regime_state(
    state_path: Path | str,
    observation: RegimeObservation,
    *,
    max_history: int = 100,
) -> None:
    """Persist the latest regime observation and history to a JSON file."""
    path = Path(state_path)
    existing = load_regime_state(state_path)
    history = list(existing.get("history", []))
    if observation.regime_id is not None:
        history.append(observation.regime_id)
    history = history[-max_history:]
    state: dict[str, Any] = {
        "version": REGIME_ROUTER_VERSION,
        "history": history,
        "last_observation": observation.to_dict(),
        "last_updated": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    atomic_write_json(path, state)
