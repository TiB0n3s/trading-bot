"""Expected-value research helpers.

This module is intentionally independent of live order routing. It answers the
research question that follows feature discrimination: does a bucket still have
positive expectancy after realistic trading friction?
"""

from __future__ import annotations

import math
import statistics
from dataclasses import dataclass
from typing import Any, Iterable


@dataclass(frozen=True)
class ExpectedValueAssumptions:
    spread_pct: float = 0.0
    slippage_pct: float = 0.0
    slippage_turns: float = 2.0
    commission_pct: float = 0.0
    account_equity: float | None = None
    max_position_pct: float = 1.0
    reference_price: float | None = None


def _finite_float(value: Any) -> float | None:
    try:
        if value in (None, ""):
            return None
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def _mean(values: list[float]) -> float | None:
    return round(statistics.mean(values), 6) if values else None


def round_trip_cost_pct(assumptions: ExpectedValueAssumptions) -> float:
    spread = max(0.0, assumptions.spread_pct)
    slippage = max(0.0, assumptions.slippage_pct) * max(0.0, assumptions.slippage_turns)
    commission = max(0.0, assumptions.commission_pct)
    return round(spread + slippage + commission, 6)


def whole_share_deployment(assumptions: ExpectedValueAssumptions) -> dict[str, Any]:
    equity = _finite_float(assumptions.account_equity)
    price = _finite_float(assumptions.reference_price)
    max_position_pct = _finite_float(assumptions.max_position_pct)
    if equity is None or price is None or max_position_pct is None:
        return {
            "target_notional": None,
            "shares": None,
            "deployed_notional": None,
            "deployment_pct": None,
            "whole_share_cash_drag_pct": None,
        }
    if equity <= 0 or price <= 0 or max_position_pct <= 0:
        return {
            "target_notional": 0.0,
            "shares": 0,
            "deployed_notional": 0.0,
            "deployment_pct": 0.0,
            "whole_share_cash_drag_pct": 100.0,
        }

    target_notional = equity * min(max_position_pct, 1.0)
    shares = int(target_notional // price)
    deployed = shares * price
    deployment_pct = deployed / target_notional * 100.0 if target_notional else 0.0
    cash_drag = max(0.0, 100.0 - deployment_pct)
    return {
        "target_notional": round(target_notional, 2),
        "shares": shares,
        "deployed_notional": round(deployed, 2),
        "deployment_pct": round(deployment_pct, 4),
        "whole_share_cash_drag_pct": round(cash_drag, 4),
    }


def evaluate_expected_value(
    returns_pct: Iterable[Any],
    *,
    assumptions: ExpectedValueAssumptions | None = None,
) -> dict[str, Any]:
    values = [value for item in returns_pct if (value := _finite_float(item)) is not None]
    assumptions = assumptions or ExpectedValueAssumptions()
    cost_pct = round_trip_cost_pct(assumptions)
    if not values:
        return {
            "runtime_effect": "research_ev_no_trade_authority",
            "n": 0,
            "win_rate_pct": None,
            "avg_win_pct": None,
            "avg_loss_pct": None,
            "gross_expected_return_pct": None,
            "round_trip_cost_pct": cost_pct,
            "net_expected_return_pct": None,
            "minimum_gross_return_to_clear_cost_pct": cost_pct,
            "profit_factor": None,
            "verdict": "no_rows",
            **whole_share_deployment(assumptions),
        }

    wins = [value for value in values if value > 0]
    losses = [value for value in values if value < 0]
    gross_ev = statistics.mean(values)
    net_ev = gross_ev - cost_pct
    gross_win_sum = sum(wins)
    gross_loss_sum = abs(sum(losses))
    profit_factor = gross_win_sum / gross_loss_sum if gross_loss_sum else None
    deployment = whole_share_deployment(assumptions)
    cash_drag = deployment.get("whole_share_cash_drag_pct")

    if deployment.get("shares") == 0:
        verdict = "cannot_deploy_whole_share"
    elif net_ev > 0:
        verdict = "positive_ev_after_costs"
    else:
        verdict = "negative_ev_after_costs"

    return {
        "runtime_effect": "research_ev_no_trade_authority",
        "n": len(values),
        "win_rate_pct": round(100.0 * len(wins) / len(values), 4),
        "avg_win_pct": _mean(wins),
        "avg_loss_pct": _mean(losses),
        "gross_expected_return_pct": round(gross_ev, 6),
        "round_trip_cost_pct": cost_pct,
        "net_expected_return_pct": round(net_ev, 6),
        "minimum_gross_return_to_clear_cost_pct": cost_pct,
        "profit_factor": round(profit_factor, 6) if profit_factor is not None else None,
        "whole_share_return_drag_pct": (
            round((cash_drag or 0.0) / 100.0 * abs(net_ev), 6)
            if cash_drag is not None and net_ev is not None
            else None
        ),
        "verdict": verdict,
        **deployment,
    }


def evaluate_decile_expected_value(
    ordered_returns_pct: Iterable[Any],
    *,
    assumptions: ExpectedValueAssumptions | None = None,
    n_buckets: int = 10,
) -> list[dict[str, Any]]:
    values = [value for item in ordered_returns_pct if (value := _finite_float(item)) is not None]
    if not values:
        return []
    n_buckets = max(1, min(int(n_buckets), len(values)))
    size = len(values) // n_buckets
    result = []
    for idx in range(n_buckets):
        lo = idx * size
        hi = len(values) if idx == n_buckets - 1 else (idx + 1) * size
        bucket = values[lo:hi]
        result.append(
            {
                "bucket": f"D{idx + 1}",
                "row_start": lo,
                "row_end": hi,
                **evaluate_expected_value(bucket, assumptions=assumptions),
            }
        )
    return result
