"""Observe-only market regime classification.

The classifier consumes already-built runtime context. It does not fetch data,
approve trades, reject trades, size orders, or submit orders.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class MarketRegimeClassification:
    trend_regime: str
    volatility_regime: str
    event_regime: str
    sector_rotation_regime: str
    liquidity_regime: str
    composite_regime: str
    confidence: str
    strategy_weights: dict[str, float]
    inputs: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _clamp(value: float, low: float = 0.0, high: float = 1.5) -> float:
    return max(low, min(high, value))


def _label(value: Any) -> str:
    return str(value or "").strip().lower()


def _base_weights() -> dict[str, float]:
    return {
        "trend_continuation": 1.0,
        "orderly_pullback": 1.0,
        "mean_reversion": 1.0,
        "momentum_chase": 1.0,
        "liquidity_sensitivity": 1.0,
    }


def _confidence(inputs_seen: int) -> str:
    if inputs_seen >= 5:
        return "medium"
    if inputs_seen >= 3:
        return "low"
    return "very_low"


def classify_market_regime(
    *,
    account_state: dict[str, Any] | None = None,
    market_context: dict[str, Any] | None = None,
) -> MarketRegimeClassification:
    """Classify the current market regime from available live context.

    The output is intentionally compact and deterministic so it can be persisted
    in canonical snapshots and used as an observe-only input to utility scoring.
    """
    account_state = _dict(account_state)
    market_context = _dict(market_context)
    macro = _dict(account_state.get("macro_risk"))
    session = _dict(account_state.get("session_momentum"))
    momentum = _dict(account_state.get("momentum"))
    tape = _dict(account_state.get("tape"))
    market_alignment = _dict(account_state.get("market_alignment"))
    rolling = _dict(account_state.get("rolling_momentum"))

    reasons: list[str] = []
    weights = _base_weights()
    inputs_seen = 0

    macro_regime = _label(macro.get("macro_regime"))
    risk_multiplier = _float(macro.get("risk_multiplier"))
    session_label = _label(session.get("trend_label"))
    session_return_pct = _float(session.get("session_return_pct"))
    distance_from_vwap_pct = _float(session.get("distance_from_vwap_pct"))
    momentum_state = _label(momentum.get("momentum_state"))
    momentum_direction = _label(momentum.get("direction"))
    volume_state = _label(momentum.get("volume_state") or tape.get("volume_state"))
    volume_surge_ratio = _float(
        momentum.get("volume_surge_ratio") or tape.get("volume_surge_ratio")
    )
    tape_classification = _label(tape.get("classification") or tape.get("tape_classification"))
    sector_alignment = _label(
        market_context.get("sector_alignment")
        or market_alignment.get("sector_alignment")
        or market_alignment.get("cluster")
    )
    breadth = _float(
        market_context.get("breadth_score") or market_context.get("market_breadth_score")
    )

    for value in (
        macro_regime,
        session_label,
        momentum_state,
        volume_state,
        sector_alignment,
        breadth,
        session_return_pct,
        distance_from_vwap_pct,
    ):
        if value not in (None, ""):
            inputs_seen += 1

    trend_regime = "mixed"
    if macro_regime in {"defensive", "capital_preservation"} or session_label in {
        "downtrend",
        "hard_negative",
    }:
        trend_regime = "risk_off_unwind"
        weights["trend_continuation"] = 0.65
        weights["orderly_pullback"] = 0.55
        weights["momentum_chase"] = 0.35
        weights["mean_reversion"] = 1.15
        reasons.append("risk-off trend context")
    elif session_label in {"strong_uptrend", "uptrend"} and macro_regime in {
        "risk_on",
        "bullish",
        "normal",
        "neutral",
        "mixed",
    }:
        trend_regime = "trend_continuation"
        weights["trend_continuation"] = 1.25
        weights["orderly_pullback"] = 1.15
        weights["mean_reversion"] = 0.75
        reasons.append("session trend supports continuation")
    elif session_label in {"fading", "reversal_attempt"}:
        trend_regime = "mean_reversion_or_fading"
        weights["trend_continuation"] = 0.75
        weights["orderly_pullback"] = 0.85
        weights["mean_reversion"] = 1.20
        weights["momentum_chase"] = 0.55
        reasons.append(f"session label={session_label}")
    elif macro_regime in {"risk_on", "bullish"}:
        trend_regime = "constructive_mixed"
        weights["trend_continuation"] = 1.10
        weights["orderly_pullback"] = 1.05
        reasons.append(f"macro_regime={macro_regime}")

    volatility_regime = "normal"
    if volume_state == "surge" or (volume_surge_ratio is not None and volume_surge_ratio >= 1.8):
        volatility_regime = "high_volatility_expansion"
        weights["trend_continuation"] = _clamp(weights["trend_continuation"] + 0.15)
        weights["momentum_chase"] = _clamp(weights["momentum_chase"] + 0.10)
        reasons.append("volume/range expansion")
    elif volume_state in {"thin", "low"} or (
        volume_surge_ratio is not None and volume_surge_ratio <= 0.55
    ):
        volatility_regime = "low_volatility_compression"
        weights["momentum_chase"] = _clamp(weights["momentum_chase"] - 0.25)
        weights["liquidity_sensitivity"] = 1.25
        reasons.append("low volume/compression")

    event_regime = "none"
    special_labels = rolling.get("special_labels") or []
    if not isinstance(special_labels, list):
        special_labels = []
    if "gap_up_chase_risk" in special_labels:
        event_regime = "event_driven_gap"
        weights["momentum_chase"] = _clamp(weights["momentum_chase"] - 0.30)
        weights["orderly_pullback"] = _clamp(weights["orderly_pullback"] + 0.10)
        reasons.append("gap_up_chase_risk")
    elif momentum_state == "accelerating" and volume_state in {"elevated", "surge"}:
        event_regime = "gap_or_news_follow_through"
        weights["trend_continuation"] = _clamp(weights["trend_continuation"] + 0.10)
        reasons.append("accelerating momentum with elevated volume")

    sector_rotation_regime = "unknown"
    if sector_alignment in {"aligned", "leading", "stable", "risk_on"}:
        sector_rotation_regime = "stable_leadership"
        weights["trend_continuation"] = _clamp(weights["trend_continuation"] + 0.05)
        reasons.append(f"sector_alignment={sector_alignment}")
    elif sector_alignment in {"mixed", "rotation", "unknown"}:
        sector_rotation_regime = "mixed_rotation"
    elif sector_alignment in {"lagging", "misaligned", "avoid"}:
        sector_rotation_regime = "unstable_rotation"
        weights["trend_continuation"] = _clamp(weights["trend_continuation"] - 0.10)
        weights["mean_reversion"] = _clamp(weights["mean_reversion"] + 0.10)
        reasons.append(f"sector_alignment={sector_alignment}")
    if breadth is not None:
        if breadth >= 65:
            sector_rotation_regime = "broad_participation"
            weights["trend_continuation"] = _clamp(weights["trend_continuation"] + 0.10)
            reasons.append(f"breadth_score={breadth:.1f}")
        elif breadth <= 35:
            sector_rotation_regime = "narrow_or_weak_breadth"
            weights["momentum_chase"] = _clamp(weights["momentum_chase"] - 0.15)
            weights["orderly_pullback"] = _clamp(weights["orderly_pullback"] - 0.10)
            reasons.append(f"weak_breadth={breadth:.1f}")

    liquidity_regime = "normal"
    if volume_state in {"thin", "low"} or tape_classification in {"thin", "illiquid"}:
        liquidity_regime = "liquidity_thin"
        weights["momentum_chase"] = _clamp(weights["momentum_chase"] - 0.25)
        weights["liquidity_sensitivity"] = 1.35
        reasons.append("liquidity thin")

    if risk_multiplier is not None and risk_multiplier < 0.8:
        weights["trend_continuation"] = _clamp(weights["trend_continuation"] - 0.10)
        weights["momentum_chase"] = _clamp(weights["momentum_chase"] - 0.15)
        reasons.append(f"risk_multiplier={risk_multiplier:.2f}")

    composite_regime = trend_regime
    if liquidity_regime == "liquidity_thin":
        composite_regime = "liquidity_constrained"
    elif volatility_regime == "high_volatility_expansion" and trend_regime == "trend_continuation":
        composite_regime = "trend_expansion"
    elif volatility_regime == "low_volatility_compression":
        composite_regime = "compression_chop"
    elif event_regime != "none":
        composite_regime = event_regime

    inputs = {
        "macro_regime": macro_regime or None,
        "risk_multiplier": risk_multiplier,
        "session_label": session_label or None,
        "session_return_pct": session_return_pct,
        "distance_from_vwap_pct": distance_from_vwap_pct,
        "momentum_state": momentum_state or None,
        "momentum_direction": momentum_direction or None,
        "volume_state": volume_state or None,
        "volume_surge_ratio": volume_surge_ratio,
        "sector_alignment": sector_alignment or None,
        "breadth_score": breadth,
    }

    return MarketRegimeClassification(
        trend_regime=trend_regime,
        volatility_regime=volatility_regime,
        event_regime=event_regime,
        sector_rotation_regime=sector_rotation_regime,
        liquidity_regime=liquidity_regime,
        composite_regime=composite_regime,
        confidence=_confidence(inputs_seen),
        strategy_weights={key: round(value, 4) for key, value in weights.items()},
        inputs=inputs,
        reasons=reasons[:12],
    )
