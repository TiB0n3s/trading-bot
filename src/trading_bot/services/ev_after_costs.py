"""Net expected value after costs — the promotion-spine EV bar.

The project's deployability bar is net EV after costs >= +0.25% per name. This
module provides a pure estimator and the bar check so the rule is encoded, not
just documented.
"""

from __future__ import annotations

DEFAULT_EV_AFTER_COST_MIN_PCT = 0.25


def estimate_net_ev_after_cost_pct(
    *,
    prob_win: float,
    reward_pct: float,
    risk_pct: float,
    extra_cost_pct: float = 0.0,
) -> float:
    """Net EV in % of notional: ``p*reward - (1-p)*risk - extra_costs``.

    ``reward_pct`` / ``risk_pct`` should ALREADY include modeled round-trip
    slippage (as the slippage-Kelly ``adjusted_*`` values do). ``extra_cost_pct``
    covers commissions/fees not already folded into spread/slippage — Alpaca
    equity commissions are $0, so SEC/TAF are the only residuals and are
    typically negligible.
    """
    p = max(0.0, min(1.0, float(prob_win)))
    return p * float(reward_pct) - (1.0 - p) * float(risk_pct) - float(extra_cost_pct)


def clears_ev_bar(net_ev_pct: float, min_pct: float = DEFAULT_EV_AFTER_COST_MIN_PCT) -> bool:
    """True if net EV after costs meets the per-name deployability bar."""
    return float(net_ev_pct) >= float(min_pct)
