"""Downside asymmetry feature classification.

This module asks how a trade usually loses. It is observe-only and has no
approval, sizing, persistence, data-fetching, or order-submission side effects.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class DownsideAsymmetryEstimate:
    downside_state: str
    gap_down_vulnerability: str
    catalyst_risk: str
    overnight_risk: str
    squeeze_risk: str
    headline_sensitivity: str
    beta_shock_sensitivity: str
    historical_mae_state: str
    failure_signature: str
    downside_score: float
    expected_adverse_modifier: float
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


def evaluate_downside_asymmetry(
    *,
    account_state: dict[str, Any] | None = None,
) -> DownsideAsymmetryEstimate:
    account_state = _dict(account_state)
    risk = _dict(account_state.get("downside_risk"))
    setup = _dict(account_state.get("setup_quality"))
    market_regime = _dict(account_state.get("market_regime"))
    macro = _dict(account_state.get("macro_risk"))

    gap_down_pct = _float(risk.get("gap_down_vulnerability_pct") or account_state.get("gap_down_vulnerability_pct"))
    earnings_days = _float(risk.get("earnings_days") or account_state.get("earnings_days"))
    catalyst_proximity = _label(risk.get("catalyst_proximity") or account_state.get("catalyst_proximity"))
    overnight_hold = bool(risk.get("overnight_hold") or account_state.get("overnight_hold"))
    short_interest_pct = _float(risk.get("short_interest_pct") or account_state.get("short_interest_pct"))
    headline_sensitivity_score = _float(
        risk.get("headline_sensitivity_score") or account_state.get("headline_sensitivity_score")
    )
    beta = _float(risk.get("beta") or account_state.get("beta") or macro.get("portfolio_beta"))
    beta_shock_loss_pct = _float(risk.get("beta_shock_loss_pct") or account_state.get("beta_shock_loss_pct"))
    historical_mae_pct = _float(
        risk.get("historical_setup_mae_pct")
        or risk.get("historical_max_adverse_excursion_pct")
        or setup.get("historical_mae_pct")
    )
    failure_pattern = _label(risk.get("failure_pattern_signature") or setup.get("failure_pattern_signature"))

    score = 0.25
    modifier = 1.0
    reasons: list[str] = []

    gap_down_vulnerability = "unknown"
    if gap_down_pct is not None:
        if gap_down_pct >= 2.0:
            gap_down_vulnerability = "high"
            score += 0.16
            modifier += 0.18
            reasons.append(f"gap_down_vulnerability={gap_down_pct:.2f}%")
        elif gap_down_pct >= 1.0:
            gap_down_vulnerability = "elevated"
            score += 0.08
            modifier += 0.08
            reasons.append(f"gap_down_vulnerability={gap_down_pct:.2f}%")
        else:
            gap_down_vulnerability = "low"

    catalyst_risk = "none_known"
    if earnings_days is not None:
        if 0 <= earnings_days <= 2:
            catalyst_risk = "imminent_earnings"
            score += 0.14
            modifier += 0.15
            reasons.append(f"earnings_days={earnings_days:.1f}")
        elif 0 <= earnings_days <= 5:
            catalyst_risk = "near_earnings"
            score += 0.07
            modifier += 0.07
            reasons.append(f"earnings_days={earnings_days:.1f}")
    if catalyst_proximity in {"imminent", "near", "same_day"}:
        catalyst_risk = f"{catalyst_proximity}_catalyst"
        score += 0.08
        modifier += 0.08
        reasons.append(f"catalyst_proximity={catalyst_proximity}")

    overnight_risk = "none"
    if overnight_hold:
        overnight_risk = "planned_overnight_hold"
        score += 0.08
        modifier += 0.08
        reasons.append("overnight_hold")

    squeeze_risk = "unknown"
    if short_interest_pct is not None:
        if short_interest_pct >= 20:
            squeeze_risk = "high_squeeze_two_sided_risk"
            score += 0.08
            modifier += 0.06
            reasons.append(f"short_interest={short_interest_pct:.1f}%")
        elif short_interest_pct >= 10:
            squeeze_risk = "elevated"
            score += 0.04
        else:
            squeeze_risk = "low"

    headline_sensitivity = "unknown"
    if headline_sensitivity_score is not None:
        if headline_sensitivity_score >= 0.70:
            headline_sensitivity = "high"
            score += 0.11
            modifier += 0.12
            reasons.append(f"headline_sensitivity={headline_sensitivity_score:.2f}")
        elif headline_sensitivity_score >= 0.40:
            headline_sensitivity = "elevated"
            score += 0.05
        else:
            headline_sensitivity = "low"

    beta_shock_sensitivity = "unknown"
    if beta_shock_loss_pct is not None:
        if beta_shock_loss_pct >= 2.0:
            beta_shock_sensitivity = "high"
            score += 0.12
            modifier += 0.12
            reasons.append(f"beta_shock_loss={beta_shock_loss_pct:.2f}%")
        elif beta_shock_loss_pct >= 1.0:
            beta_shock_sensitivity = "elevated"
            score += 0.06
    elif beta is not None:
        if beta >= 1.6:
            beta_shock_sensitivity = "high_beta"
            score += 0.08
            modifier += 0.08
            reasons.append(f"beta={beta:.2f}")
        elif beta >= 1.2:
            beta_shock_sensitivity = "elevated_beta"
            score += 0.04
        else:
            beta_shock_sensitivity = "normal"

    historical_mae_state = "unknown"
    if historical_mae_pct is not None:
        if abs(historical_mae_pct) >= 2.0:
            historical_mae_state = "large_historical_mae"
            score += 0.12
            modifier += 0.12
            reasons.append(f"historical_mae={historical_mae_pct:.2f}%")
        elif abs(historical_mae_pct) >= 1.0:
            historical_mae_state = "elevated_historical_mae"
            score += 0.06
        else:
            historical_mae_state = "contained_historical_mae"

    failure_signature = "unknown"
    if failure_pattern:
        failure_signature = failure_pattern
        if any(token in failure_pattern for token in ("failed_breakout", "gap_reject", "vwap_loss")):
            score += 0.09
            modifier += 0.08
            reasons.append(f"failure_signature={failure_pattern}")

    regime = _label(market_regime.get("composite_regime"))
    if regime in {"risk_off_unwind", "liquidity_constrained"}:
        score += 0.08
        modifier += 0.08
        reasons.append(f"regime_downside={regime}")

    final_score = _clamp(score)
    if final_score >= 0.65:
        downside_state = "asymmetric_downside_high"
    elif final_score >= 0.42:
        downside_state = "asymmetric_downside_elevated"
    else:
        downside_state = "downside_contained_or_unknown"

    return DownsideAsymmetryEstimate(
        downside_state=downside_state,
        gap_down_vulnerability=gap_down_vulnerability,
        catalyst_risk=catalyst_risk,
        overnight_risk=overnight_risk,
        squeeze_risk=squeeze_risk,
        headline_sensitivity=headline_sensitivity,
        beta_shock_sensitivity=beta_shock_sensitivity,
        historical_mae_state=historical_mae_state,
        failure_signature=failure_signature,
        downside_score=round(final_score, 4),
        expected_adverse_modifier=round(max(1.0, min(1.75, modifier)), 4),
        inputs={
            "gap_down_vulnerability_pct": gap_down_pct,
            "earnings_days": earnings_days,
            "catalyst_proximity": catalyst_proximity or None,
            "overnight_hold": overnight_hold,
            "short_interest_pct": short_interest_pct,
            "headline_sensitivity_score": headline_sensitivity_score,
            "beta": beta,
            "beta_shock_loss_pct": beta_shock_loss_pct,
            "historical_mae_pct": historical_mae_pct,
            "failure_pattern_signature": failure_pattern or None,
        },
        reasons=reasons[:12],
    )
