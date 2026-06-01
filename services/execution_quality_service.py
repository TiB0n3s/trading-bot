"""Execution quality estimation for pre-trade decisioning.

This module estimates whether expected edge survives spread, slippage, quote
instability, and signal-to-executable price drift. It is deterministic and has
no broker, DB, or order-submission side effects.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class ExecutionQualityEstimate:
    decision: str
    fill_quality: str
    size_multiplier: float
    spread_pct: float | None
    spread_cost_pct: float
    slippage_estimate_pct: float
    fees_pct: float
    signal_executable_gap_pct: float | None
    quote_instability_score: float
    top_of_book_depth_score: float | None
    expected_fill_quality_score: float
    sweep_risk: str
    forecast_edge_pct: float | None
    net_execution_cost_pct: float
    net_edge_after_cost_pct: float | None
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


def _spread_from_quote(quote: dict[str, Any]) -> float | None:
    bid = _float(quote.get("bid"))
    ask = _float(quote.get("ask"))
    if bid is None or ask is None or bid <= 0 or ask <= 0:
        return None
    if ask <= bid:
        return 0.0
    mid = (bid + ask) / 2.0
    if mid <= 0:
        return None
    return (ask - bid) / mid * 100.0


def _gap_pct(action: str, signal_price: Any, quote: dict[str, Any], latest_price: Any) -> float | None:
    signal = _float(signal_price)
    if signal is None or signal <= 0:
        return None
    executable = None
    if action == "buy":
        executable = _float(quote.get("ask"))
    elif action == "sell":
        executable = _float(quote.get("bid"))
    if executable is None:
        executable = _float(latest_price)
    if executable is None or executable <= 0:
        return None
    if action == "sell":
        return (signal - executable) / signal * 100.0
    return (executable - signal) / signal * 100.0


def estimate_execution_quality(
    *,
    symbol: str | None = None,
    action: str,
    signal_price: Any = None,
    account_state: dict[str, Any] | None = None,
    quote_snapshot: dict[str, Any] | None = None,
    latest_price: Any = None,
    fees_pct: float = 0.01,
    forecast_edge_pct: Any = None,
) -> ExecutionQualityEstimate:
    """Estimate execution quality and net execution cost for a signal."""
    action = (action or "").lower()
    account_state = _dict(account_state)
    quote = _dict(quote_snapshot) or _dict(account_state.get("quote_snapshot"))
    second_look = _dict(account_state.get("second_look"))
    tape = _dict(account_state.get("tape"))
    momentum = _dict(account_state.get("momentum"))
    reasons: list[str] = []

    spread_pct = (
        _float(quote.get("spread_pct"))
        or _float(second_look.get("spread_pct"))
        or _float(account_state.get("spread_pct"))
        or _spread_from_quote(quote)
    )
    spread_cost_pct = max(0.0, (spread_pct or 0.0) / 2.0)

    gap_pct = _gap_pct(
        action,
        signal_price if signal_price is not None else account_state.get("signal_price"),
        quote,
        latest_price if latest_price is not None else account_state.get("latest_price"),
    )

    volume_state = str(
        momentum.get("volume_state")
        or tape.get("volume_state")
        or account_state.get("volume_state")
        or ""
    ).lower()
    if volume_state in {"thin", "low"}:
        liquidity_penalty = 0.10
        reasons.append(f"low_liquidity_volume_state={volume_state}")
    elif volume_state == "surge":
        liquidity_penalty = 0.04
        reasons.append("surge_volume_sweep_risk")
    else:
        liquidity_penalty = 0.03

    quote_instability_score = 0.0
    if quote.get("suspect_quote") or second_look.get("suspect_quote"):
        quote_instability_score += 0.45
        reasons.append("suspect_quote")
    attempts = _float(quote.get("attempts") or second_look.get("attempts"))
    if attempts and attempts > 1:
        quote_instability_score += min(0.30, (attempts - 1) * 0.10)
        reasons.append(f"quote_retry_attempts={int(attempts)}")
    tape_age = _float(account_state.get("tape_bar_age_seconds") or tape.get("tape_bar_age_seconds"))
    if tape_age is not None and tape_age > 75:
        quote_instability_score += 0.20
        reasons.append(f"stale_tape_age={tape_age:.1f}s")
    quote_instability_score = _clamp(quote_instability_score)

    bid_size = _float(quote.get("bid_size"))
    ask_size = _float(quote.get("ask_size"))
    intended_qty = _float(account_state.get("intended_qty") or account_state.get("qty"))
    depth_score = None
    if intended_qty and intended_qty > 0:
        book_size = ask_size if action == "buy" else bid_size
        if book_size is not None:
            depth_score = _clamp(book_size / intended_qty)
            if depth_score < 0.5:
                reasons.append(f"top_of_book_depth_low={depth_score:.2f}")

    slippage_estimate_pct = liquidity_penalty
    slippage_estimate_pct += (spread_pct or 0.0) * 0.25
    slippage_estimate_pct += quote_instability_score * 0.12
    if depth_score is not None and depth_score < 1.0:
        slippage_estimate_pct += (1.0 - depth_score) * 0.10
    if gap_pct is not None and gap_pct > 0:
        slippage_estimate_pct += min(0.25, gap_pct * 0.35)

    net_cost = round(spread_cost_pct + slippage_estimate_pct + float(fees_pct or 0.0), 4)
    forecast_edge = _float(
        forecast_edge_pct
        if forecast_edge_pct is not None
        else account_state.get("forecast_edge_pct")
        or account_state.get("expected_value_pct")
        or (_dict(account_state.get("utility_estimate")).get("expected_value_pct"))
        or (_dict(account_state.get("decision_policy")).get("expected_value_pct"))
    )
    net_edge_after_cost = (
        round(forecast_edge - net_cost, 4) if forecast_edge is not None else None
    )
    expected_fill_quality_score = _clamp(1.0 - net_cost / 1.5)

    sweep_risk = "low"
    if quote_instability_score >= 0.45 or volume_state == "surge":
        sweep_risk = "medium"
    if quote_instability_score >= 0.70 or (spread_pct is not None and spread_pct >= 0.75):
        sweep_risk = "high"

    decision = "allow"
    size_multiplier = 1.0
    fill_quality = "good"
    if net_cost >= 0.90 or sweep_risk == "high":
        decision = "block"
        size_multiplier = 0.0
        fill_quality = "poor"
        reasons.append(f"net_execution_cost={net_cost:.3f}%")
    elif net_cost >= 0.35 or expected_fill_quality_score < 0.75:
        decision = "size_down"
        size_multiplier = 0.75 if net_cost < 0.60 else 0.50
        fill_quality = "degraded"
        reasons.append(f"net_execution_cost={net_cost:.3f}%")
    elif net_edge_after_cost is not None and net_edge_after_cost <= 0:
        decision = "size_down"
        size_multiplier = 0.75
        fill_quality = "edge_eroded"
        reasons.append(f"net_edge_after_cost={net_edge_after_cost:.3f}%")
    else:
        reasons.append("execution_quality_acceptable")

    return ExecutionQualityEstimate(
        decision=decision,
        fill_quality=fill_quality,
        size_multiplier=size_multiplier,
        spread_pct=round(spread_pct, 4) if spread_pct is not None else None,
        spread_cost_pct=round(spread_cost_pct, 4),
        slippage_estimate_pct=round(slippage_estimate_pct, 4),
        fees_pct=round(float(fees_pct or 0.0), 4),
        signal_executable_gap_pct=round(gap_pct, 4) if gap_pct is not None else None,
        quote_instability_score=round(quote_instability_score, 4),
        top_of_book_depth_score=round(depth_score, 4) if depth_score is not None else None,
        expected_fill_quality_score=round(expected_fill_quality_score, 4),
        sweep_risk=sweep_risk,
        forecast_edge_pct=round(forecast_edge, 4) if forecast_edge is not None else None,
        net_execution_cost_pct=net_cost,
        net_edge_after_cost_pct=net_edge_after_cost,
        reasons=reasons[:12],
    )
