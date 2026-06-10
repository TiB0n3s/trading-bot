"""Volatility-normalized signal feature classification.

This module converts raw movement, spread, gap, and stop distances into
ATR/realized-volatility context. It is observe-only and has no data-fetching,
approval, sizing, persistence, or order-submission side effects.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class VolatilityNormalizationFeatures:
    stretch_state: str
    entry_distance_atr: float | None
    move_zscore: float | None
    range_percentile: float | None
    gap_percentile: float | None
    spread_atr_pct: float | None
    stop_excursion_ratio: float | None
    volatility_regime: str
    chase_risk: str
    stop_quality: str
    volatility_adjusted_score: float
    expectancy_modifier: float
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


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _safe_div(numerator: float | None, denominator: float | None) -> float | None:
    if numerator is None or denominator is None or denominator <= 0:
        return None
    return numerator / denominator


def _abs_pct_distance(a: float | None, b: float | None) -> float | None:
    if a is None or b is None or b <= 0:
        return None
    return abs(a - b) / b * 100.0


def classify_volatility_normalization(
    *,
    account_state: dict[str, Any] | None = None,
) -> VolatilityNormalizationFeatures:
    """Build volatility-normalized features from available signal context."""
    account_state = _dict(account_state)
    session = _dict(account_state.get("session_momentum"))
    intraday = _dict(account_state.get("intraday_microstructure"))
    rolling = _dict(account_state.get("rolling_momentum"))
    execution_quality = _dict(account_state.get("execution_quality"))
    setup = _dict(account_state.get("setup_quality") or account_state.get("setup_observation"))
    volatility_inputs = _dict(account_state.get("volatility_inputs"))

    price = _float(
        account_state.get("latest_price")
        or account_state.get("signal_price")
        or volatility_inputs.get("price")
    )
    entry_reference = _float(
        volatility_inputs.get("entry_reference_price")
        or account_state.get("entry_reference_price")
        or account_state.get("prior_close")
        or session.get("vwap")
    )
    atr_pct = _float(
        volatility_inputs.get("atr_pct")
        or account_state.get("atr_pct")
        or session.get("atr_pct")
        or rolling.get("atr_pct")
    )
    atr_price = _float(
        volatility_inputs.get("atr")
        or account_state.get("atr")
        or session.get("atr")
        or rolling.get("atr")
    )
    if atr_pct is None and atr_price is not None and price and price > 0:
        atr_pct = atr_price / price * 100.0
    realized_vol_pct = _float(
        volatility_inputs.get("realized_volatility_pct")
        or intraday.get("realized_volatility_pct")
        or session.get("realized_volatility_pct")
        or rolling.get("realized_volatility_pct")
    )
    move_pct = _float(
        volatility_inputs.get("move_pct")
        or account_state.get("momentum_pct")
        or (_dict(account_state.get("momentum")).get("momentum_pct"))
        or session.get("session_return_pct")
    )
    range_percentile = _float(
        volatility_inputs.get("range_percentile")
        or intraday.get("range_percentile")
        or session.get("range_percentile")
        or rolling.get("range_percentile")
    )
    gap_pct = _float(
        volatility_inputs.get("gap_pct")
        or intraday.get("opening_gap_pct")
        or session.get("opening_gap_pct")
    )
    gap_percentile = _float(
        volatility_inputs.get("gap_percentile")
        or intraday.get("gap_percentile")
        or session.get("gap_percentile")
    )
    spread_pct = _float(
        volatility_inputs.get("spread_pct")
        or execution_quality.get("spread_pct")
        or account_state.get("spread_pct")
    )
    stop_distance_pct = _float(
        volatility_inputs.get("stop_distance_pct")
        or account_state.get("stop_distance_pct")
        or setup.get("stop_distance_pct")
    )
    expected_adverse_excursion_pct = _float(
        volatility_inputs.get("expected_adverse_excursion_pct")
        or account_state.get("expected_adverse_excursion_pct")
        or (_dict(account_state.get("utility_estimate")).get("expected_adverse_excursion_pct"))
        or (_dict(account_state.get("decision_policy")).get("utility_estimate") or {}).get(
            "expected_adverse_excursion_pct"
        )
    )

    entry_distance_pct = _abs_pct_distance(price, entry_reference)
    entry_distance_atr = _safe_div(entry_distance_pct, atr_pct)
    move_zscore = _safe_div(move_pct, realized_vol_pct or atr_pct)
    spread_atr_pct = _safe_div(spread_pct, atr_pct)
    stop_excursion_ratio = _safe_div(stop_distance_pct, expected_adverse_excursion_pct)

    score = 0.50
    expectancy_modifier = 1.0
    reasons: list[str] = []

    stretch_state = "unknown"
    if entry_distance_atr is not None:
        if entry_distance_atr >= 2.0:
            stretch_state = "extreme_stretch"
            score -= 0.16
            expectancy_modifier -= 0.16
            reasons.append(f"entry_distance_atr={entry_distance_atr:.2f}")
        elif entry_distance_atr >= 1.25:
            stretch_state = "stretched"
            score -= 0.09
            expectancy_modifier -= 0.09
            reasons.append(f"entry_distance_atr={entry_distance_atr:.2f}")
        elif entry_distance_atr <= 0.50:
            stretch_state = "near_reference"
            score += 0.04
            reasons.append(f"entry_distance_atr={entry_distance_atr:.2f}")
        else:
            stretch_state = "normal"

    if move_zscore is not None:
        abs_z = abs(move_zscore)
        if abs_z >= 2.5:
            score -= 0.12
            expectancy_modifier -= 0.12
            reasons.append(f"move_zscore_extreme={move_zscore:.2f}")
        elif abs_z >= 1.5:
            score -= 0.05
            expectancy_modifier -= 0.04
            reasons.append(f"move_zscore_elevated={move_zscore:.2f}")
        elif abs_z <= 0.75:
            score += 0.03

    if range_percentile is not None:
        if range_percentile >= 90:
            score -= 0.09
            expectancy_modifier -= 0.08
            reasons.append(f"range_percentile_high={range_percentile:.1f}")
        elif range_percentile <= 25:
            score += 0.03
            reasons.append(f"range_percentile_low={range_percentile:.1f}")

    if gap_percentile is not None:
        if gap_percentile >= 90:
            score -= 0.08
            expectancy_modifier -= 0.08
            reasons.append(f"gap_percentile_high={gap_percentile:.1f}")
        elif gap_percentile <= 35:
            score += 0.02
    elif gap_pct is not None and atr_pct is not None:
        gap_atr = abs(gap_pct) / atr_pct if atr_pct > 0 else None
        if gap_atr is not None and gap_atr >= 1.5:
            score -= 0.07
            expectancy_modifier -= 0.06
            reasons.append(f"gap_atr={gap_atr:.2f}")

    if spread_atr_pct is not None:
        if spread_atr_pct >= 0.25:
            score -= 0.10
            expectancy_modifier -= 0.10
            reasons.append(f"spread_atr_pct={spread_atr_pct:.2f}")
        elif spread_atr_pct <= 0.08:
            score += 0.03

    stop_quality = "unknown"
    if stop_excursion_ratio is not None:
        if stop_excursion_ratio < 0.70:
            stop_quality = "too_tight_vs_excursion"
            score -= 0.07
            expectancy_modifier -= 0.06
            reasons.append(f"stop_excursion_ratio={stop_excursion_ratio:.2f}")
        elif stop_excursion_ratio > 1.80:
            stop_quality = "too_wide_vs_excursion"
            score -= 0.06
            expectancy_modifier -= 0.05
            reasons.append(f"stop_excursion_ratio={stop_excursion_ratio:.2f}")
        else:
            stop_quality = "aligned_with_excursion"
            score += 0.04

    volatility_regime = "unknown"
    vol_basis = realized_vol_pct if realized_vol_pct is not None else atr_pct
    if vol_basis is not None:
        if vol_basis >= 2.0:
            volatility_regime = "high_volatility"
            score -= 0.04
            reasons.append(f"volatility_basis={vol_basis:.2f}%")
        elif vol_basis <= 0.45:
            volatility_regime = "compressed_volatility"
            score -= 0.02
            reasons.append(f"volatility_basis={vol_basis:.2f}%")
        else:
            volatility_regime = "normal"

    chase_risk = "normal"
    if stretch_state == "extreme_stretch" or (move_zscore is not None and abs(move_zscore) >= 2.5):
        chase_risk = "high"
    elif stretch_state == "stretched" or (move_zscore is not None and abs(move_zscore) >= 1.5):
        chase_risk = "elevated"
    if range_percentile is not None and range_percentile >= 90:
        chase_risk = "high"

    inputs = {
        "price": price,
        "entry_reference_price": entry_reference,
        "atr_pct": atr_pct,
        "atr": atr_price,
        "realized_volatility_pct": realized_vol_pct,
        "move_pct": move_pct,
        "range_percentile": range_percentile,
        "gap_pct": gap_pct,
        "gap_percentile": gap_percentile,
        "spread_pct": spread_pct,
        "stop_distance_pct": stop_distance_pct,
        "expected_adverse_excursion_pct": expected_adverse_excursion_pct,
    }

    return VolatilityNormalizationFeatures(
        stretch_state=stretch_state,
        entry_distance_atr=round(entry_distance_atr, 4) if entry_distance_atr is not None else None,
        move_zscore=round(move_zscore, 4) if move_zscore is not None else None,
        range_percentile=round(range_percentile, 4) if range_percentile is not None else None,
        gap_percentile=round(gap_percentile, 4) if gap_percentile is not None else None,
        spread_atr_pct=round(spread_atr_pct, 4) if spread_atr_pct is not None else None,
        stop_excursion_ratio=round(stop_excursion_ratio, 4)
        if stop_excursion_ratio is not None
        else None,
        volatility_regime=volatility_regime,
        chase_risk=chase_risk,
        stop_quality=stop_quality,
        volatility_adjusted_score=round(_clamp(score), 4),
        expectancy_modifier=round(max(0.55, min(1.25, expectancy_modifier)), 4),
        inputs=inputs,
        reasons=reasons[:12],
    )
