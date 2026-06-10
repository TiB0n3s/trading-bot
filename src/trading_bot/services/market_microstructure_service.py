"""Time-of-day and market microstructure feature classification.

This module consumes already-built runtime context. It does not fetch data,
approve trades, reject trades, size orders, or submit orders.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any


@dataclass(frozen=True)
class MarketMicrostructureFeatures:
    session_phase: str
    opening_range_state: str
    gap_state: str
    vwap_state: str
    liquidity_state: str
    intraday_volatility_state: str
    compression_state: str
    auction_quality: str
    breakout_quality: str
    reversion_risk: str
    microstructure_score: float
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


def _label(value: Any) -> str:
    return str(value or "").strip().lower()


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def _minutes_since_open(value: Any) -> int | None:
    raw = _float(value)
    if raw is not None:
        return int(raw)
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except Exception:
        return None
    return parsed.hour * 60 + parsed.minute - (9 * 60 + 30)


def _session_phase(minutes_since_open: int | None) -> str:
    if minutes_since_open is None:
        return "unknown"
    if minutes_since_open < 0:
        return "pre_market"
    if minutes_since_open <= 5:
        return "opening_auction"
    if minutes_since_open <= 15:
        return "first_15m"
    if minutes_since_open <= 30:
        return "first_30m"
    if minutes_since_open < 150:
        return "morning_trend"
    if minutes_since_open < 300:
        return "midday"
    if minutes_since_open <= 390:
        return "power_hour"
    return "after_hours"


def classify_market_microstructure(
    *,
    account_state: dict[str, Any] | None = None,
) -> MarketMicrostructureFeatures:
    """Classify microstructure conditions from available signal context."""
    account_state = _dict(account_state)
    session = _dict(account_state.get("session_momentum"))
    momentum = _dict(account_state.get("momentum"))
    tape = _dict(account_state.get("tape"))
    rolling = _dict(account_state.get("rolling_momentum"))
    intraday = _dict(account_state.get("intraday_microstructure"))
    opening = _dict(account_state.get("opening_range"))

    minutes = _minutes_since_open(
        account_state.get("minutes_since_open")
        or intraday.get("minutes_since_open")
        or account_state.get("market_minutes_since_open")
        or account_state.get("received_at")
        or account_state.get("timestamp")
    )
    phase = _session_phase(minutes)

    price = _float(account_state.get("latest_price") or account_state.get("signal_price"))
    open_high = _float(
        opening.get("high")
        or intraday.get("opening_range_high")
        or session.get("opening_range_high")
    )
    open_low = _float(
        opening.get("low") or intraday.get("opening_range_low") or session.get("opening_range_low")
    )
    first_5_return = _float(
        intraday.get("first_5m_return_pct") or session.get("first_5m_return_pct")
    )
    first_15_return = _float(
        intraday.get("first_15m_return_pct") or session.get("first_15m_return_pct")
    )
    first_30_return = _float(
        intraday.get("first_30m_return_pct") or session.get("first_30m_return_pct")
    )
    gap_pct = _float(intraday.get("opening_gap_pct") or session.get("opening_gap_pct"))
    gap_hold_pct = _float(intraday.get("gap_hold_pct") or session.get("gap_hold_pct"))
    distance_from_vwap = _float(
        intraday.get("distance_from_vwap_pct")
        or session.get("distance_from_vwap_pct")
        or account_state.get("session_distance_from_vwap_pct")
    )
    volume_state = _label(momentum.get("volume_state") or tape.get("volume_state"))
    volume_surge_ratio = _float(
        momentum.get("volume_surge_ratio") or tape.get("volume_surge_ratio")
    )
    realized_vol = _float(
        intraday.get("realized_volatility_pct")
        or session.get("realized_volatility_pct")
        or rolling.get("realized_volatility_pct")
    )
    range_expansion_ratio = _float(
        intraday.get("range_expansion_ratio")
        or session.get("range_expansion_ratio")
        or rolling.get("range_expansion_ratio")
    )
    bar_overlap_ratio = _float(
        intraday.get("bar_overlap_ratio")
        or session.get("bar_overlap_ratio")
        or rolling.get("bar_overlap_ratio")
    )
    wick_ratio = _float(
        intraday.get("wick_ratio") or session.get("wick_ratio") or rolling.get("wick_ratio")
    )

    reasons: list[str] = []
    score = 0.50
    expectancy_modifier = 1.0

    opening_range_state = "unknown"
    if price is not None and open_high is not None and open_low is not None:
        if price > open_high:
            opening_range_state = "above_opening_range"
            score += 0.08
            reasons.append("price_above_opening_range")
        elif price < open_low:
            opening_range_state = "below_opening_range"
            score -= 0.10
            reasons.append("price_below_opening_range")
        else:
            opening_range_state = "inside_opening_range"
            score -= 0.03
            reasons.append("price_inside_opening_range")

    gap_state = "none_or_unknown"
    if gap_pct is not None:
        if abs(gap_pct) < 0.25:
            gap_state = "flat_open"
        elif gap_pct > 0:
            if gap_hold_pct is not None and gap_hold_pct >= 0.50:
                gap_state = "gap_up_accepted"
                score += 0.07
                reasons.append("opening_gap_accepted")
            elif gap_hold_pct is not None and gap_hold_pct <= -0.25:
                gap_state = "gap_up_rejected"
                score -= 0.10
                reasons.append("opening_gap_rejected")
            else:
                gap_state = "gap_up_unconfirmed"
                score -= 0.02
        else:
            gap_state = "gap_down"
            score -= 0.04

    vwap_state = "unknown"
    if distance_from_vwap is not None:
        if distance_from_vwap >= 1.5:
            vwap_state = "stretched_above_vwap"
            score -= 0.06
            expectancy_modifier -= 0.08
            reasons.append("vwap_stretch_reversion_risk")
        elif distance_from_vwap >= 0.15:
            vwap_state = "above_vwap"
            score += 0.03
            reasons.append("above_vwap")
        elif distance_from_vwap <= -1.5:
            vwap_state = "stretched_below_vwap"
            score -= 0.04
            reasons.append("stretched_below_vwap")
        elif distance_from_vwap <= -0.15:
            vwap_state = "below_vwap"
            score -= 0.04
            reasons.append("below_vwap")
        else:
            vwap_state = "near_vwap"
            score += 0.02
            reasons.append("near_vwap")

    liquidity_state = "normal"
    if phase == "midday":
        liquidity_state = "midday_liquidity_decay"
        score -= 0.06
        expectancy_modifier -= 0.08
        reasons.append("midday_liquidity_decay")
    if volume_state in {"thin", "low"} or (
        volume_surge_ratio is not None and volume_surge_ratio <= 0.55
    ):
        liquidity_state = "liquidity_vacuum"
        score -= 0.10
        expectancy_modifier -= 0.12
        reasons.append("liquidity_vacuum")
    elif volume_state in {"elevated", "surge"} or (
        volume_surge_ratio is not None and volume_surge_ratio >= 1.5
    ):
        liquidity_state = "volume_expansion"
        score += 0.07
        expectancy_modifier += 0.08
        reasons.append("volume_expansion")

    intraday_volatility_state = "normal"
    if range_expansion_ratio is not None and range_expansion_ratio >= 1.4:
        intraday_volatility_state = "range_expansion"
        score += 0.05
        reasons.append("range_expansion")
    elif range_expansion_ratio is not None and range_expansion_ratio <= 0.65:
        intraday_volatility_state = "range_compression"
        score -= 0.04
        reasons.append("range_compression")
    elif realized_vol is not None and realized_vol >= 1.2:
        intraday_volatility_state = "high_realized_volatility"
        score -= 0.03
        reasons.append("high_realized_volatility")

    compression_state = "normal"
    if bar_overlap_ratio is not None and bar_overlap_ratio >= 0.65:
        compression_state = "overlapping_chop"
        score -= 0.10
        expectancy_modifier -= 0.10
        reasons.append("high_bar_overlap")
    elif bar_overlap_ratio is not None and bar_overlap_ratio <= 0.30:
        compression_state = "directional_bars"
        score += 0.05
        reasons.append("directional_bars")

    auction_quality = "normal"
    if wick_ratio is not None and wick_ratio >= 0.55:
        auction_quality = "failed_auction_wicky"
        score -= 0.09
        expectancy_modifier -= 0.08
        reasons.append("wicky_failed_auction")
    elif wick_ratio is not None and wick_ratio <= 0.25:
        auction_quality = "clean_auction"
        score += 0.04
        reasons.append("clean_auction")

    breakout_quality = "neutral"
    if opening_range_state == "above_opening_range" and liquidity_state == "volume_expansion":
        breakout_quality = "confirmed_expansion_breakout"
        score += 0.08
        expectancy_modifier += 0.10
        reasons.append("breakout_on_volume_expansion")
    elif opening_range_state == "above_opening_range" and liquidity_state in {
        "midday_liquidity_decay",
        "liquidity_vacuum",
    }:
        breakout_quality = "liquidity_vacuum_breakout"
        score -= 0.10
        expectancy_modifier -= 0.15
        reasons.append("breakout_in_liquidity_vacuum")
    elif phase == "power_hour" and intraday_volatility_state == "range_expansion":
        breakout_quality = "power_hour_expansion"
        score += 0.06
        expectancy_modifier += 0.06
        reasons.append("power_hour_expansion")

    reversion_risk = "normal"
    if vwap_state in {"stretched_above_vwap", "stretched_below_vwap"}:
        reversion_risk = "elevated"
    if compression_state == "overlapping_chop" or auction_quality == "failed_auction_wicky":
        reversion_risk = "high"

    inputs = {
        "minutes_since_open": minutes,
        "first_5m_return_pct": first_5_return,
        "first_15m_return_pct": first_15_return,
        "first_30m_return_pct": first_30_return,
        "opening_gap_pct": gap_pct,
        "gap_hold_pct": gap_hold_pct,
        "distance_from_vwap_pct": distance_from_vwap,
        "volume_state": volume_state or None,
        "volume_surge_ratio": volume_surge_ratio,
        "range_expansion_ratio": range_expansion_ratio,
        "realized_volatility_pct": realized_vol,
        "bar_overlap_ratio": bar_overlap_ratio,
        "wick_ratio": wick_ratio,
    }

    return MarketMicrostructureFeatures(
        session_phase=phase,
        opening_range_state=opening_range_state,
        gap_state=gap_state,
        vwap_state=vwap_state,
        liquidity_state=liquidity_state,
        intraday_volatility_state=intraday_volatility_state,
        compression_state=compression_state,
        auction_quality=auction_quality,
        breakout_quality=breakout_quality,
        reversion_risk=reversion_risk,
        microstructure_score=round(_clamp(score), 4),
        expectancy_modifier=round(max(0.50, min(1.35, expectancy_modifier)), 4),
        inputs=inputs,
        reasons=reasons[:12],
    )
