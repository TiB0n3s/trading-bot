"""Regime-aware ML sub-model routing layer.

Routes incoming signals to the appropriate sub-model slot based on the current
regime observation. Each regime triggers a different strategy profile:

  Regime 0 (quiet_bull)         → RandomForest trend-continuation model
  Regime 1 (choppy_range)       → oscillator / mean-reversion model
  Regime 2 (high_volatility)    → stand-down; route to crash protocol

This module emits routing decisions only. It does not submit orders, call the
broker, approve or reject signals, or modify live authority.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from services.regime_switching_service import RegimeObservation

REGIME_ROUTER_ROUTING_VERSION = "regime_model_router_v1"

# Per-regime sub-model configuration.
# Keys are canonical regime IDs (0, 1, 2).
_REGIME_SUB_MODELS: dict[int, dict[str, Any]] = {
    0: {
        "model_slot": "regime_0_model",
        "sub_model_strategy": "random_forest_trend_continuation",
        "scoring_bias": "long_bias",
        "size_modifier": 1.0,
        "allow_new_longs": True,
        "allow_new_shorts": False,
        "signal_filter": "momentum_and_trend_confirmation",
        "description": "Quiet bull: trend-following, full size, long-only",
    },
    1: {
        "model_slot": "regime_1_model",
        "sub_model_strategy": "oscillator_mean_reversion",
        "scoring_bias": "mean_reversion",
        "size_modifier": 0.65,
        "allow_new_longs": True,
        "allow_new_shorts": False,
        "signal_filter": "rsi_extremes_and_vwap_distance",
        "description": "Choppy: oscillator signals, reduced size, avoid chasing",
    },
    2: {
        "model_slot": "regime_2_model",
        "sub_model_strategy": "crash_standdown",
        "scoring_bias": "stand_down",
        "size_modifier": 0.0,
        "allow_new_longs": False,
        "allow_new_shorts": True,
        "signal_filter": "none",
        "description": "High-vol crash: no new longs, hedge via SPY short",
    },
}

_UNSTABLE_CONFIG: dict[str, Any] = {
    "model_slot": "no_model_regime_unstable",
    "sub_model_strategy": "stand_down_unstable_regime",
    "scoring_bias": "stand_down",
    "size_modifier": 0.0,
    "allow_new_longs": False,
    "allow_new_shorts": False,
    "signal_filter": "none",
    "description": "Regime not yet stable: stand down until smoothing window confirms",
}

_NO_DATA_CONFIG: dict[str, Any] = {
    "model_slot": "no_model_insufficient_data",
    "sub_model_strategy": "stand_down_no_data",
    "scoring_bias": "stand_down",
    "size_modifier": 0.0,
    "allow_new_longs": False,
    "allow_new_shorts": False,
    "signal_filter": "none",
    "description": "Insufficient data for regime detection",
}


@dataclass(frozen=True)
class RegimeRoutingDecision:
    version: str
    regime_id: int | None
    regime_label: str
    active_model_slot: str
    sub_model_strategy: str
    scoring_bias: str
    size_modifier: float
    allow_new_longs: bool
    allow_new_shorts: bool
    signal_filter: str
    confidence: str
    runtime_effect: str
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def route_to_model(
    regime_obs: RegimeObservation,
) -> RegimeRoutingDecision:
    """Route to the appropriate sub-model based on the regime observation.

    Returns a ``RegimeRoutingDecision`` that describes which model slot is
    active and how signals should be filtered or sized in this regime. The
    ``runtime_effect`` is always ``observe_only_no_order_authority``.
    """
    reasons = list(regime_obs.reasons)

    if regime_obs.regime_id is None:
        cfg = _NO_DATA_CONFIG
        reasons.append("regime_id=None: routing to no-data stand-down")
        return _make_decision(regime_obs, cfg, confidence="none", reasons=reasons)

    if not regime_obs.stable:
        cfg = _UNSTABLE_CONFIG
        reasons.append(
            f"regime={regime_obs.regime_id} not yet stable: routing to unstable stand-down"
        )
        return _make_decision(regime_obs, cfg, confidence="low", reasons=reasons)

    cfg = _REGIME_SUB_MODELS.get(regime_obs.regime_id, _UNSTABLE_CONFIG)
    reasons.append(f"routing_to={cfg['model_slot']}")
    return _make_decision(regime_obs, cfg, confidence=regime_obs.confidence, reasons=reasons)


def _make_decision(
    obs: RegimeObservation,
    cfg: dict[str, Any],
    *,
    confidence: str,
    reasons: list[str],
) -> RegimeRoutingDecision:
    return RegimeRoutingDecision(
        version=REGIME_ROUTER_ROUTING_VERSION,
        regime_id=obs.regime_id,
        regime_label=obs.regime_label,
        active_model_slot=cfg["model_slot"],
        sub_model_strategy=cfg["sub_model_strategy"],
        scoring_bias=cfg["scoring_bias"],
        size_modifier=cfg["size_modifier"],
        allow_new_longs=cfg["allow_new_longs"],
        allow_new_shorts=cfg["allow_new_shorts"],
        signal_filter=cfg["signal_filter"],
        confidence=confidence,
        runtime_effect="observe_only_no_order_authority",
        reasons=reasons[:12],
    )


def routing_matrix_summary() -> dict[str, Any]:
    """Return a human-readable summary of the full routing matrix."""
    return {
        "version": REGIME_ROUTER_ROUTING_VERSION,
        "runtime_effect": "observe_only_no_order_authority",
        "regimes": {
            str(k): {
                "model_slot": v["model_slot"],
                "sub_model_strategy": v["sub_model_strategy"],
                "scoring_bias": v["scoring_bias"],
                "size_modifier": v["size_modifier"],
                "allow_new_longs": v["allow_new_longs"],
                "signal_filter": v["signal_filter"],
                "description": v["description"],
            }
            for k, v in _REGIME_SUB_MODELS.items()
        },
    }
