"""Structural setup-quality classification.

This module scores chart structure separately from trend/momentum language. It
does not fetch data, approve trades, reject trades, size orders, or persist rows.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class SetupStructureScore:
    structure_state: str
    base_quality: str
    failed_breakout_risk: str
    compression_expansion_state: str
    htf_location_state: str
    anchored_vwap_state: str
    gap_context_state: str
    retest_quality: str
    reward_risk_state: str
    structure_score: float
    expectancy_modifier: float
    inputs: dict[str, Any] = field(default_factory=dict)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except Exception:
        return None


def _int(value: Any) -> int | None:
    try:
        if value is None:
            return None
        return int(value)
    except Exception:
        return None


def _label(value: Any) -> str:
    return str(value or "").strip().lower()


def _clamp(value: float, low: float = 0.0, high: float = 1.0) -> float:
    return max(low, min(high, value))


def evaluate_setup_structure(snapshot: dict[str, Any] | None) -> SetupStructureScore:
    """Score setup structure from live feature/setup snapshot fields."""
    snapshot = snapshot if isinstance(snapshot, dict) else {}
    reasons: list[str] = []
    score = 0.50
    expectancy_modifier = 1.0

    base_type = _label(snapshot.get("base_type") or snapshot.get("range_quality"))
    bar_overlap = _float(snapshot.get("bar_overlap_ratio"))
    wick_ratio = _float(snapshot.get("wick_ratio"))
    failed_breakouts = _int(
        snapshot.get("prior_failed_breakouts")
        or snapshot.get("failed_breakout_count")
        or snapshot.get("failed_breakouts_20d")
    )
    compression_ratio = _float(
        snapshot.get("compression_ratio")
        or snapshot.get("volatility_compression_ratio")
        or snapshot.get("range_compression_ratio")
    )
    expansion_ratio = _float(
        snapshot.get("expansion_ratio")
        or snapshot.get("range_expansion_ratio")
        or snapshot.get("volume_expansion_ratio")
    )
    distance_to_resistance_pct = _float(
        snapshot.get("distance_to_resistance_pct") or snapshot.get("next_supply_distance_pct")
    )
    distance_to_support_pct = _float(
        snapshot.get("distance_to_support_pct") or snapshot.get("nearest_support_distance_pct")
    )
    anchored_vwap_distance_pct = _float(
        snapshot.get("anchored_vwap_distance_pct")
        or snapshot.get("distance_from_anchored_vwap_pct")
    )
    gap_hold_pct = _float(snapshot.get("gap_hold_pct"))
    gap_pct = _float(snapshot.get("opening_gap_pct") or snapshot.get("gap_pct"))
    retest_hold_pct = _float(snapshot.get("retest_hold_pct"))
    retest_volume_ratio = _float(snapshot.get("retest_volume_ratio"))
    reward_risk_ratio = _float(
        snapshot.get("reward_risk_ratio")
        or snapshot.get("reward_to_risk")
        or snapshot.get("rr_before_supply")
    )

    base_quality = "unknown"
    if base_type in {"clean", "tight", "flat_base", "constructive"}:
        base_quality = "clean_base"
        score += 0.13
        expectancy_modifier += 0.08
        reasons.append(f"base_quality={base_type}")
    elif base_type in {"messy", "wide", "choppy", "volatile"}:
        base_quality = "messy_range"
        score -= 0.13
        expectancy_modifier -= 0.10
        reasons.append(f"base_quality={base_type}")
    elif bar_overlap is not None:
        if bar_overlap >= 0.70 or (wick_ratio is not None and wick_ratio >= 0.55):
            base_quality = "messy_range"
            score -= 0.10
            expectancy_modifier -= 0.08
            reasons.append("messy_overlap_or_wicks")
        elif bar_overlap <= 0.35:
            base_quality = "clean_base"
            score += 0.08
            reasons.append("low_bar_overlap")

    failed_breakout_risk = "unknown"
    if failed_breakouts is not None:
        if failed_breakouts >= 2:
            failed_breakout_risk = "high"
            score -= 0.13
            expectancy_modifier -= 0.10
            reasons.append(f"prior_failed_breakouts={failed_breakouts}")
        elif failed_breakouts == 1:
            failed_breakout_risk = "elevated"
            score -= 0.06
            reasons.append("one_prior_failed_breakout")
        else:
            failed_breakout_risk = "low"
            score += 0.04

    compression_expansion_state = "unknown"
    if compression_ratio is not None and expansion_ratio is not None:
        if compression_ratio <= 0.70 and expansion_ratio >= 1.25:
            compression_expansion_state = "compression_into_expansion"
            score += 0.14
            expectancy_modifier += 0.10
            reasons.append("compression_before_expansion")
        elif compression_ratio >= 1.10 and expansion_ratio <= 0.85:
            compression_expansion_state = "no_clean_expansion"
            score -= 0.08
            reasons.append("no_compression_expansion_edge")

    htf_location_state = "unknown"
    if distance_to_resistance_pct is not None:
        if distance_to_resistance_pct < 0.45:
            htf_location_state = "crowded_below_supply"
            score -= 0.12
            expectancy_modifier -= 0.12
            reasons.append(f"supply_too_close={distance_to_resistance_pct:.2f}%")
        elif distance_to_resistance_pct >= 1.5:
            htf_location_state = "room_to_supply"
            score += 0.08
            expectancy_modifier += 0.08
            reasons.append(f"room_to_supply={distance_to_resistance_pct:.2f}%")
    if distance_to_support_pct is not None and distance_to_support_pct <= 0.35:
        if htf_location_state == "unknown":
            htf_location_state = "support_nearby"
        score += 0.05
        reasons.append(f"support_nearby={distance_to_support_pct:.2f}%")

    anchored_vwap_state = "unknown"
    if anchored_vwap_distance_pct is not None:
        if abs(anchored_vwap_distance_pct) <= 0.35:
            anchored_vwap_state = "near_anchored_vwap"
            score += 0.06
            reasons.append("near_anchored_vwap")
        elif anchored_vwap_distance_pct > 2.0:
            anchored_vwap_state = "extended_above_anchored_vwap"
            score -= 0.08
            expectancy_modifier -= 0.06
            reasons.append(f"extended_above_avwap={anchored_vwap_distance_pct:.2f}%")
        elif anchored_vwap_distance_pct < -1.0:
            anchored_vwap_state = "below_anchored_vwap"
            score -= 0.06
            reasons.append(f"below_avwap={anchored_vwap_distance_pct:.2f}%")

    gap_context_state = "unknown"
    if gap_pct is not None:
        if gap_pct > 0 and gap_hold_pct is not None and gap_hold_pct >= 0.50:
            gap_context_state = "gap_accepted"
            score += 0.06
            reasons.append("gap_accepted")
        elif gap_pct > 0 and gap_hold_pct is not None and gap_hold_pct <= -0.25:
            gap_context_state = "gap_rejected"
            score -= 0.10
            expectancy_modifier -= 0.08
            reasons.append("gap_rejected")
        elif abs(gap_pct) >= 1.5:
            gap_context_state = "large_unconfirmed_gap"
            score -= 0.05
            reasons.append("large_unconfirmed_gap")

    retest_quality = "unknown"
    if retest_hold_pct is not None:
        if retest_hold_pct >= 0 and (retest_volume_ratio is None or retest_volume_ratio <= 0.95):
            retest_quality = "constructive_retest"
            score += 0.08
            expectancy_modifier += 0.05
            reasons.append("constructive_retest")
        elif retest_hold_pct < -0.20:
            retest_quality = "failed_retest"
            score -= 0.10
            expectancy_modifier -= 0.08
            reasons.append("failed_retest")

    reward_risk_state = "unknown"
    if reward_risk_ratio is not None:
        if reward_risk_ratio >= 2.0:
            reward_risk_state = "favorable_rr"
            score += 0.12
            expectancy_modifier += 0.10
            reasons.append(f"reward_risk={reward_risk_ratio:.2f}")
        elif reward_risk_ratio < 1.2:
            reward_risk_state = "poor_rr"
            score -= 0.12
            expectancy_modifier -= 0.12
            reasons.append(f"poor_reward_risk={reward_risk_ratio:.2f}")
        else:
            reward_risk_state = "adequate_rr"

    adjusted_score = _clamp(score)
    if adjusted_score >= 0.72:
        structure_state = "high_quality_structure"
    elif adjusted_score <= 0.38:
        structure_state = "poor_structure"
    else:
        structure_state = "mixed_structure"

    return SetupStructureScore(
        structure_state=structure_state,
        base_quality=base_quality,
        failed_breakout_risk=failed_breakout_risk,
        compression_expansion_state=compression_expansion_state,
        htf_location_state=htf_location_state,
        anchored_vwap_state=anchored_vwap_state,
        gap_context_state=gap_context_state,
        retest_quality=retest_quality,
        reward_risk_state=reward_risk_state,
        structure_score=round(adjusted_score, 4),
        expectancy_modifier=round(max(0.55, min(1.30, expectancy_modifier)), 4),
        inputs={
            "base_type": base_type or None,
            "bar_overlap_ratio": bar_overlap,
            "wick_ratio": wick_ratio,
            "prior_failed_breakouts": failed_breakouts,
            "compression_ratio": compression_ratio,
            "expansion_ratio": expansion_ratio,
            "distance_to_resistance_pct": distance_to_resistance_pct,
            "distance_to_support_pct": distance_to_support_pct,
            "anchored_vwap_distance_pct": anchored_vwap_distance_pct,
            "gap_pct": gap_pct,
            "gap_hold_pct": gap_hold_pct,
            "retest_hold_pct": retest_hold_pct,
            "retest_volume_ratio": retest_volume_ratio,
            "reward_risk_ratio": reward_risk_ratio,
        },
        reasons=reasons[:12],
    )
