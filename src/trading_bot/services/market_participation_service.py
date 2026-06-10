"""Market breadth and relative-strength participation classification.

This module consumes already-built runtime context. It does not fetch market
data, approve trades, reject trades, size orders, or submit orders.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class MarketParticipationEstimate:
    participation_state: str
    sector_relative_strength_state: str
    peer_confirmation_state: str
    breadth_state: str
    index_participation_state: str
    leader_laggard_state: str
    relative_volume_state: str
    confirmation_score: float
    isolated_move_risk: str
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


def _state_from_score(value: float | None, *, high: float, low: float) -> str:
    if value is None:
        return "unknown"
    if value >= high:
        return "supportive"
    if value <= low:
        return "weak"
    return "mixed"


def evaluate_market_participation(
    *,
    account_state: dict[str, Any] | None = None,
    market_context: dict[str, Any] | None = None,
) -> MarketParticipationEstimate:
    """Evaluate whether the symbol move is confirmed by market/peer context."""
    account_state = _dict(account_state)
    market_context = _dict(market_context)
    alignment = _dict(account_state.get("market_alignment"))
    momentum = _dict(account_state.get("momentum"))
    tape = _dict(account_state.get("tape"))
    participation = _dict(account_state.get("market_participation_inputs"))

    sector_rs = _float(
        participation.get("sector_relative_strength_pct")
        or alignment.get("sector_relative_strength_pct")
        or market_context.get("sector_relative_strength_pct")
    )
    industry_breadth = _float(
        participation.get("industry_group_breadth_pct")
        or alignment.get("industry_group_breadth_pct")
        or market_context.get("industry_group_breadth_pct")
    )
    peers_above_vwap = _float(
        participation.get("peers_above_vwap_pct")
        or alignment.get("peers_above_vwap_pct")
        or market_context.get("peers_above_vwap_pct")
    )
    peers_above_ma = _float(
        participation.get("peers_above_key_ma_pct")
        or alignment.get("peers_above_key_ma_pct")
        or market_context.get("peers_above_key_ma_pct")
    )
    market_breadth = _float(
        participation.get("market_breadth_score")
        or market_context.get("market_breadth_score")
        or market_context.get("breadth_score")
    )
    index_participation = _float(
        participation.get("index_participation_pct")
        or market_context.get("index_participation_pct")
    )
    relative_volume_vs_peers = _float(
        participation.get("relative_volume_vs_peers")
        or alignment.get("relative_volume_vs_peers")
        or market_context.get("relative_volume_vs_peers")
    )
    symbol_rs = _float(
        participation.get("symbol_relative_strength_pct")
        or alignment.get("symbol_relative_strength_pct")
        or momentum.get("relative_strength_pct")
    )
    peer_median_rs = _float(
        participation.get("peer_median_relative_strength_pct")
        or alignment.get("peer_median_relative_strength_pct")
    )
    sector_alignment = _label(
        market_context.get("sector_alignment")
        or alignment.get("sector_alignment")
        or alignment.get("cluster")
    )
    market_internals = _label(
        participation.get("market_internals")
        or market_context.get("market_internals")
        or market_context.get("internals")
    )
    volume_state = _label(momentum.get("volume_state") or tape.get("volume_state"))

    reasons: list[str] = []
    score = 0.50
    expectancy_modifier = 1.0

    sector_state = _state_from_score(sector_rs, high=0.35, low=-0.35)
    if sector_state == "supportive":
        score += 0.10
        expectancy_modifier += 0.08
        reasons.append(f"sector_rs_supportive={sector_rs:.2f}%")
    elif sector_state == "weak":
        score -= 0.12
        expectancy_modifier -= 0.10
        reasons.append(f"sector_rs_weak={sector_rs:.2f}%")
    elif sector_alignment in {"leading", "aligned", "stable", "risk_on"}:
        sector_state = "supportive"
        score += 0.06
        reasons.append(f"sector_alignment={sector_alignment}")
    elif sector_alignment in {"lagging", "misaligned", "avoid"}:
        sector_state = "weak"
        score -= 0.08
        reasons.append(f"sector_alignment={sector_alignment}")

    breadth_inputs = [
        value for value in (industry_breadth, peers_above_vwap, peers_above_ma) if value is not None
    ]
    peer_breadth = sum(breadth_inputs) / len(breadth_inputs) if breadth_inputs else None
    peer_state = _state_from_score(peer_breadth, high=60.0, low=40.0)
    if peer_state == "supportive":
        score += 0.12
        expectancy_modifier += 0.08
        reasons.append(f"peer_breadth_supportive={peer_breadth:.1f}%")
    elif peer_state == "weak":
        score -= 0.14
        expectancy_modifier -= 0.12
        reasons.append(f"peer_breadth_weak={peer_breadth:.1f}%")

    breadth_state = _state_from_score(market_breadth, high=60.0, low=40.0)
    if breadth_state == "supportive":
        score += 0.07
        reasons.append(f"market_breadth_supportive={market_breadth:.1f}")
    elif breadth_state == "weak":
        score -= 0.10
        expectancy_modifier -= 0.06
        reasons.append(f"market_breadth_weak={market_breadth:.1f}")
    if market_internals in {"positive", "supportive", "risk_on"}:
        score += 0.05
        reasons.append(f"market_internals={market_internals}")
    elif market_internals in {"negative", "weak", "risk_off"}:
        score -= 0.07
        reasons.append(f"market_internals={market_internals}")

    index_state = _state_from_score(index_participation, high=60.0, low=40.0)
    if index_state == "supportive":
        score += 0.06
        reasons.append(f"index_participation={index_participation:.1f}%")
    elif index_state == "weak":
        score -= 0.08
        expectancy_modifier -= 0.05
        reasons.append(f"weak_index_participation={index_participation:.1f}%")

    leader_laggard_state = "unknown"
    if symbol_rs is not None and peer_median_rs is not None:
        rs_delta = symbol_rs - peer_median_rs
        if rs_delta >= 0.50:
            leader_laggard_state = "leader_confirmed"
            score += 0.08
            reasons.append(f"leader_vs_peers={rs_delta:.2f}%")
        elif rs_delta <= -0.50:
            leader_laggard_state = "laggard"
            score -= 0.10
            expectancy_modifier -= 0.08
            reasons.append(f"laggard_vs_peers={rs_delta:.2f}%")
        else:
            leader_laggard_state = "inline_with_peers"

    relative_volume_state = "unknown"
    if relative_volume_vs_peers is not None:
        if relative_volume_vs_peers >= 1.25:
            relative_volume_state = "confirming_relative_volume"
            score += 0.06
            reasons.append(f"relative_volume_vs_peers={relative_volume_vs_peers:.2f}")
        elif relative_volume_vs_peers <= 0.75:
            relative_volume_state = "weak_relative_volume"
            score -= 0.08
            expectancy_modifier -= 0.06
            reasons.append(f"weak_relative_volume_vs_peers={relative_volume_vs_peers:.2f}")
    elif volume_state in {"elevated", "surge"}:
        relative_volume_state = "symbol_volume_elevated"
        score += 0.03

    confirmation_score = round(_clamp(score), 4)
    if confirmation_score >= 0.68:
        participation_state = "confirmed"
    elif confirmation_score <= 0.38:
        participation_state = "isolated_or_weak"
    else:
        participation_state = "mixed"

    isolated_move_risk = "normal"
    if peer_state == "weak" and breadth_state == "weak":
        isolated_move_risk = "high"
    elif peer_state == "weak" or breadth_state == "weak":
        isolated_move_risk = "elevated"
    if participation_state == "confirmed":
        isolated_move_risk = "low"

    inputs = {
        "sector_relative_strength_pct": sector_rs,
        "industry_group_breadth_pct": industry_breadth,
        "peers_above_vwap_pct": peers_above_vwap,
        "peers_above_key_ma_pct": peers_above_ma,
        "market_breadth_score": market_breadth,
        "index_participation_pct": index_participation,
        "relative_volume_vs_peers": relative_volume_vs_peers,
        "symbol_relative_strength_pct": symbol_rs,
        "peer_median_relative_strength_pct": peer_median_rs,
        "sector_alignment": sector_alignment or None,
        "market_internals": market_internals or None,
    }

    return MarketParticipationEstimate(
        participation_state=participation_state,
        sector_relative_strength_state=sector_state,
        peer_confirmation_state=peer_state,
        breadth_state=breadth_state,
        index_participation_state=index_state,
        leader_laggard_state=leader_laggard_state,
        relative_volume_state=relative_volume_state,
        confirmation_score=confirmation_score,
        isolated_move_risk=isolated_move_risk,
        expectancy_modifier=round(max(0.55, min(1.30, expectancy_modifier)), 4),
        inputs=inputs,
        reasons=reasons[:12],
    )
