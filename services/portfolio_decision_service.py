"""Portfolio-level duplicate-risk decisioning.

This module evaluates whether a candidate trade adds useful exposure or mostly
duplicates existing portfolio risk. It is deterministic and side-effect free.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from symbols_config import CLUSTER_EXPOSURE_LIMITS, SYMBOL_CONFIG


DEFAULT_FACTOR_LIMITS = {
    "mega_cap_tech": 18.0,
    "ai_infra": 16.0,
    "semiconductors": 14.0,
    "software_infra": 12.0,
    "hardware_infra": 10.0,
    "consumer_growth": 12.0,
    "broad_index": 18.0,
}

DEFAULT_BETA = {
    "broad_index": 1.0,
    "hedge": 0.2,
    "defensive": 0.55,
    "telecom": 0.65,
    "consumer": 0.85,
    "healthcare": 0.80,
    "energy": 0.95,
    "financials": 1.05,
    "industrials": 1.10,
    "mega_cap_tech": 1.20,
    "software_infra": 1.25,
    "hardware_infra": 1.30,
    "semiconductors": 1.45,
    "ai_infra": 1.50,
    "consumer_growth": 1.35,
}

STRESS_CORRELATION = {
    "broad_index": 0.90,
    "mega_cap_tech": 0.82,
    "ai_infra": 0.86,
    "semiconductors": 0.88,
    "software_infra": 0.78,
    "hardware_infra": 0.78,
    "consumer_growth": 0.75,
    "financials": 0.70,
    "industrials": 0.68,
    "energy": 0.62,
    "healthcare": 0.52,
    "defensive": 0.40,
    "hedge": -0.20,
}


@dataclass(frozen=True)
class PortfolioDecision:
    decision: str
    size_multiplier: float
    duplicate_risk_score: float
    incremental_position_pct: float
    incremental_var_pct: float
    beta_contribution_delta: float
    factor_overlap_score: float
    sector_concentration_delta_pct: float
    downside_comovement_score: float
    max_cluster_exposure_after_pct: float
    max_cluster_name: str | None
    crowded_theme: str | None
    overlap_symbols: list[str] = field(default_factory=list)
    cluster_deltas: list[dict[str, Any]] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _dict(value: Any) -> dict[str, Any]:
    return value if isinstance(value, dict) else {}


def _float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except Exception:
        return default


def _position_symbol(position: Any) -> str | None:
    if isinstance(position, dict):
        raw = position.get("symbol")
    else:
        raw = getattr(position, "symbol", None)
    return str(raw).upper() if raw else None


def _position_value(position: Any) -> float:
    if isinstance(position, dict):
        return _float(position.get("market_value"))
    return _float(getattr(position, "market_value", None))


def _position_qty(position: Any) -> float:
    if isinstance(position, dict):
        return _float(position.get("qty"))
    return _float(getattr(position, "qty", None))


def _clusters(symbol: str | None) -> list[str]:
    if not symbol:
        return []
    return list((SYMBOL_CONFIG.get(symbol.upper()) or {}).get("clusters") or [])


def _symbol_beta(symbol: str) -> float:
    clusters = _clusters(symbol)
    if not clusters:
        return 1.0
    return max(DEFAULT_BETA.get(cluster, 1.0) for cluster in clusters)


def _stress_correlation(cluster: str) -> float:
    return STRESS_CORRELATION.get(cluster, 0.60)


def _candidate_position_pct(account_state: dict[str, Any]) -> float:
    for key in (
        "decision_policy_max_position_size_pct",
        "max_position_size_pct_override",
        "max_position_size_pct",
        "position_size_pct",
        "proposed_position_size_pct",
    ):
        value = account_state.get(key)
        if value is not None:
            return max(0.0, _float(value, 1.0))
    return 1.0


def evaluate_portfolio_decision(
    *,
    symbol: str,
    action: str,
    account_state: dict[str, Any] | None = None,
    cluster_limits: dict[str, float] | None = None,
    factor_limits: dict[str, float] | None = None,
    max_beta_delta: float = 1.25,
    max_incremental_var_pct: float = 1.8,
) -> PortfolioDecision:
    """Evaluate whether a candidate trade duplicates existing portfolio risk."""
    action = (action or "").lower()
    account_state = _dict(account_state)
    symbol = str(symbol or "").upper()

    if action != "buy" or not symbol:
        return PortfolioDecision(
            decision="not_applicable",
            size_multiplier=1.0,
            duplicate_risk_score=0.0,
            incremental_position_pct=0.0,
            incremental_var_pct=0.0,
            beta_contribution_delta=0.0,
            factor_overlap_score=0.0,
            sector_concentration_delta_pct=0.0,
            downside_comovement_score=0.0,
            max_cluster_exposure_after_pct=0.0,
            max_cluster_name=None,
            crowded_theme=None,
            reasons=["portfolio duplicate-risk check applies to buy signals only"],
        )

    cluster_limits = cluster_limits or CLUSTER_EXPOSURE_LIMITS
    factor_limits = factor_limits or DEFAULT_FACTOR_LIMITS
    balance = _float(
        account_state.get("balance")
        or account_state.get("portfolio_value")
        or account_state.get("equity"),
        0.0,
    )
    positions = (
        account_state.get("open_positions")
        or account_state.get("positions")
        or []
    )
    if balance <= 0:
        return PortfolioDecision(
            decision="allow",
            size_multiplier=1.0,
            duplicate_risk_score=0.0,
            incremental_position_pct=_candidate_position_pct(account_state),
            incremental_var_pct=0.0,
            beta_contribution_delta=0.0,
            factor_overlap_score=0.0,
            sector_concentration_delta_pct=0.0,
            downside_comovement_score=0.0,
            max_cluster_exposure_after_pct=0.0,
            max_cluster_name=None,
            crowded_theme=None,
            reasons=["portfolio balance unavailable; portfolio decision is informational only"],
        )

    candidate_clusters = _clusters(symbol)
    incremental_pct = _candidate_position_pct(account_state)
    cluster_values: dict[str, float] = {}
    overlap_symbols: list[str] = []

    for position in positions:
        held_symbol = _position_symbol(position)
        if not held_symbol:
            continue
        qty = _position_qty(position)
        market_value = _position_value(position)
        if qty <= 0 or market_value <= 0:
            continue
        held_clusters = _clusters(held_symbol)
        if set(held_clusters) & set(candidate_clusters):
            overlap_symbols.append(held_symbol)
        for cluster in held_clusters:
            cluster_values[cluster] = cluster_values.get(cluster, 0.0) + market_value

    cluster_deltas = []
    max_after = 0.0
    max_cluster = None
    crowded_theme = None
    reasons: list[str] = []
    duplicate_risk_score = 0.0

    for cluster in candidate_clusters:
        current_pct = cluster_values.get(cluster, 0.0) / balance * 100.0
        after_pct = current_pct + incremental_pct
        limit_pct = float(cluster_limits.get(cluster, factor_limits.get(cluster, 100.0)))
        factor_limit_pct = float(factor_limits.get(cluster, limit_pct))
        limit_used = min(limit_pct, factor_limit_pct)
        limit_utilization = after_pct / limit_used if limit_used > 0 else 0.0
        stress_corr = _stress_correlation(cluster)
        cluster_delta = {
            "cluster": cluster,
            "current_exposure_pct": round(current_pct, 4),
            "after_exposure_pct": round(after_pct, 4),
            "limit_pct": round(limit_used, 4),
            "limit_utilization": round(limit_utilization, 4),
            "stress_correlation": stress_corr,
        }
        cluster_deltas.append(cluster_delta)
        if after_pct > max_after:
            max_after = after_pct
            max_cluster = cluster
        if limit_utilization >= 1.0 and crowded_theme is None:
            crowded_theme = cluster
        duplicate_risk_score += max(0.0, limit_utilization - 0.65) * stress_corr

    overlap_count = len(set(overlap_symbols))
    factor_overlap_score = 0.0
    if overlap_count:
        factor_overlap_score = min(1.0, overlap_count * 0.20)
        duplicate_risk_score += min(0.50, overlap_count * 0.12)
        reasons.append(f"overlaps_existing_names={','.join(sorted(set(overlap_symbols))[:6])}")

    beta_delta = incremental_pct * _symbol_beta(symbol)
    incremental_var_pct = 0.0
    if candidate_clusters:
        avg_stress_corr = sum(_stress_correlation(c) for c in candidate_clusters) / len(candidate_clusters)
        incremental_var_pct = incremental_pct * (0.60 + avg_stress_corr)
    downside_comovement_score = round(
        min(1.0, (incremental_var_pct / max_incremental_var_pct) if max_incremental_var_pct > 0 else 0.0),
        4,
    )
    sector_concentration_delta_pct = round(max_after - incremental_pct, 4) if max_after else 0.0

    if crowded_theme:
        reasons.append(f"crowded_theme={crowded_theme}")
    if beta_delta > max_beta_delta:
        reasons.append(f"beta_delta={beta_delta:.2f} > max={max_beta_delta:.2f}")
    if incremental_var_pct > max_incremental_var_pct:
        reasons.append(
            f"incremental_var={incremental_var_pct:.2f}% > max={max_incremental_var_pct:.2f}%"
        )

    decision = "allow"
    size_multiplier = 1.0
    if crowded_theme or beta_delta > max_beta_delta * 1.5:
        decision = "block"
        size_multiplier = 0.0
    elif duplicate_risk_score >= 0.45 or beta_delta > max_beta_delta or incremental_var_pct > max_incremental_var_pct:
        decision = "size_down"
        size_multiplier = 0.50 if duplicate_risk_score >= 0.75 else 0.75

    if decision == "allow":
        reasons.append("portfolio duplicate risk acceptable")
    elif decision == "size_down":
        reasons.append(f"portfolio duplicate risk suggests size_down={size_multiplier:.2f}")
    else:
        reasons.append("portfolio duplicate risk suggests block")

    return PortfolioDecision(
        decision=decision,
        size_multiplier=size_multiplier,
        duplicate_risk_score=round(duplicate_risk_score, 4),
        incremental_position_pct=round(incremental_pct, 4),
        incremental_var_pct=round(incremental_var_pct, 4),
        beta_contribution_delta=round(beta_delta, 4),
        factor_overlap_score=round(factor_overlap_score, 4),
        sector_concentration_delta_pct=sector_concentration_delta_pct,
        downside_comovement_score=downside_comovement_score,
        max_cluster_exposure_after_pct=round(max_after, 4),
        max_cluster_name=max_cluster,
        crowded_theme=crowded_theme,
        overlap_symbols=sorted(set(overlap_symbols)),
        cluster_deltas=cluster_deltas,
        reasons=reasons[:12],
    )
