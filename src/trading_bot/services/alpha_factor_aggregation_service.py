"""Aggregate independent alpha-factor evidence into a utility input."""

from __future__ import annotations

from typing import Any

ALPHA_FACTOR_AGGREGATION_VERSION = "alpha_factor_aggregation_v1"


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        result = float(value)
    except Exception:
        return None
    return result if result == result else None


def _score(value: Any, *, scale: float = 1.0) -> float | None:
    parsed = _float(value)
    if parsed is None:
        return None
    if parsed > 1.0 and scale != 1.0:
        parsed = parsed / scale
    return max(0.0, min(1.0, parsed))


def aggregate_alpha_factors(account_state: dict[str, Any] | None = None) -> dict[str, Any]:
    account_state = _dict(account_state)
    factors: list[dict[str, Any]] = []

    bar = _dict(account_state.get("bar_pattern_features"))
    pattern_score = _score(bar.get("pattern_score"), scale=100.0)
    if pattern_score is not None:
        factors.append(
            {
                "name": "bar_pattern_structure",
                "score": pattern_score,
                "weight": 0.18,
                "direction": "support",
            }
        )
    long_score = _score(bar.get("long_opportunity_score"), scale=100.0)
    if long_score is not None:
        factors.append(
            {
                "name": "triple_barrier_long_opportunity",
                "score": long_score,
                "weight": 0.20,
                "direction": "support",
            }
        )
    toxicity = _score(bar.get("vpin_toxicity_20"))
    if toxicity is not None:
        factors.append(
            {
                "name": "vpin_toxicity",
                "score": 1.0 - toxicity,
                "weight": 0.18,
                "direction": "risk_inverse",
            }
        )

    prediction = _dict(account_state.get("prediction_gate"))
    prediction_score = _score(
        prediction.get("ml_prediction_score") or account_state.get("prediction_score"),
        scale=100.0,
    )
    if prediction_score is not None:
        factors.append(
            {
                "name": "supervised_prediction",
                "score": prediction_score,
                "weight": 0.20,
                "direction": "support",
            }
        )

    regime = _dict(account_state.get("market_regime"))
    trend_weight = _float(_dict(regime.get("strategy_weights")).get("trend_continuation"))
    if trend_weight is not None:
        factors.append(
            {
                "name": "regime_trend_fit",
                "score": max(0.0, min(1.0, trend_weight / 1.5)),
                "weight": 0.12,
                "direction": "support",
            }
        )

    value_chain = _dict(account_state.get("value_chain_eco_cluster"))
    relationship = _score(value_chain.get("max_relationship_weight"))
    if relationship is not None:
        factors.append(
            {
                "name": "value_chain_eco_cluster",
                "score": relationship,
                "weight": 0.06,
                "direction": "context",
            }
        )

    alternative = _dict(account_state.get("alternative_data_gate"))
    alt_score = _score(alternative.get("composite_score"))
    if alt_score is not None:
        factors.append(
            {
                "name": "alternative_data_gate",
                "score": alt_score,
                "weight": 0.06,
                "direction": "support",
            }
        )

    if not factors:
        return {
            "version": ALPHA_FACTOR_AGGREGATION_VERSION,
            "runtime_effect": "utility_context_no_order_authority",
            "status": "missing",
            "aggregate_score": None,
            "expectancy_modifier": 1.0,
            "factor_count": 0,
            "factors": [],
            "reason": "no alpha factors available",
        }

    total_weight = sum(float(row["weight"]) for row in factors)
    aggregate = (
        sum(float(row["score"]) * float(row["weight"]) for row in factors) / total_weight
        if total_weight > 0
        else 0.5
    )
    modifier = 0.80 + aggregate * 0.40
    return {
        "version": ALPHA_FACTOR_AGGREGATION_VERSION,
        "runtime_effect": "utility_context_no_order_authority",
        "status": "scored",
        "aggregate_score": round(aggregate, 6),
        "expectancy_modifier": round(modifier, 6),
        "factor_count": len(factors),
        "factors": factors,
        "reason": "alpha factors aggregated for utility telemetry",
    }
