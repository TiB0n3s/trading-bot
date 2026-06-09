"""Enforced live-risk gates for broker-adjacent order routing."""

from __future__ import annotations

import os
from typing import Any

from services.decision.trace import GateResult

DEFAULT_DAILY_LOSS_LIMIT_PCT = -3.0
DEFAULT_MAX_DRAWDOWN_PCT = 3.0


def _float(value: Any) -> float | None:
    try:
        if value is None or value == "":
            return None
        return float(value)
    except Exception:
        return None


def _nested(account_state: dict[str, Any], key: str) -> Any:
    account = account_state.get("account") if isinstance(account_state, dict) else {}
    if isinstance(account, dict) and account.get(key) is not None:
        return account.get(key)
    return account_state.get(key)


def _drawdown_pct(account_state: dict[str, Any]) -> float | None:
    for key in (
        "max_drawdown_pct",
        "intraday_drawdown_pct",
        "drawdown_pct",
        "daily_drawdown_pct",
    ):
        value = _float(_nested(account_state, key))
        if value is not None:
            return abs(value)
    return None


def max_drawdown_limit_pct() -> float:
    return float(
        os.getenv(
            "MAX_DRAWDOWN_LIVE_CIRCUIT_BREAKER_PCT",
            str(DEFAULT_MAX_DRAWDOWN_PCT),
        )
    )


def evaluate_live_circuit_breaker(
    *,
    action: str,
    account_state: dict[str, Any],
    daily_loss_limit_pct: float = DEFAULT_DAILY_LOSS_LIMIT_PCT,
    max_drawdown_pct: float | None = None,
) -> GateResult:
    """Block new buys when daily loss or drawdown limits are breached."""
    max_drawdown_pct = max_drawdown_limit_pct() if max_drawdown_pct is None else max_drawdown_pct
    action_l = str(action or "").strip().lower()
    if action_l != "buy":
        return GateResult(
            gate_id="live_circuit_breaker",
            layer="risk",
            decision="pass",
            authority="live",
            enforced=True,
            reason="sell/non-buy action bypasses buy-side live circuit breaker",
            inputs={"action": action_l},
        )

    daily_pnl_pct = _float(_nested(account_state, "daily_pnl_pct"))
    if daily_pnl_pct is not None and daily_pnl_pct <= daily_loss_limit_pct:
        return GateResult(
            gate_id="live_circuit_breaker",
            layer="risk",
            decision="block",
            authority="live",
            enforced=True,
            reason=(
                f"daily_pnl_pct {daily_pnl_pct:.2f}% <= "
                f"daily_loss_limit_pct {daily_loss_limit_pct:.2f}%"
            ),
            inputs={
                "action": action_l,
                "daily_pnl_pct": daily_pnl_pct,
                "daily_loss_limit_pct": daily_loss_limit_pct,
            },
        )

    drawdown_pct = _drawdown_pct(account_state)
    if drawdown_pct is not None and drawdown_pct >= max_drawdown_pct:
        return GateResult(
            gate_id="live_circuit_breaker",
            layer="risk",
            decision="block",
            authority="live",
            enforced=True,
            reason=(f"max_drawdown_pct {drawdown_pct:.2f}% >= limit {max_drawdown_pct:.2f}%"),
            inputs={
                "action": action_l,
                "drawdown_pct": drawdown_pct,
                "max_drawdown_limit_pct": max_drawdown_pct,
            },
        )

    return GateResult(
        gate_id="live_circuit_breaker",
        layer="risk",
        decision="pass",
        authority="live",
        enforced=True,
        reason="daily loss and drawdown limits clear",
        inputs={
            "action": action_l,
            "daily_pnl_pct": daily_pnl_pct,
            "drawdown_pct": drawdown_pct,
            "daily_loss_limit_pct": daily_loss_limit_pct,
            "max_drawdown_limit_pct": max_drawdown_pct,
        },
    )


def evaluate_execution_quality_live_gate(
    *,
    action: str,
    account_state: dict[str, Any],
) -> GateResult:
    """Promote execution_quality.block into a final enforced live gate."""
    execution_quality = account_state.get("execution_quality")
    execution_quality = execution_quality if isinstance(execution_quality, dict) else {}
    decision = str(execution_quality.get("decision") or "").strip().lower()
    if str(action or "").strip().lower() == "buy" and decision == "block":
        return GateResult(
            gate_id="execution_quality",
            layer="execution",
            decision="block",
            authority="live",
            enforced=True,
            reason=str(
                execution_quality.get("reason")
                or "execution_quality.block blocks buy order routing"
            ),
            inputs=execution_quality,
        )

    return GateResult(
        gate_id="execution_quality",
        layer="execution",
        decision="pass" if decision in {"allow", "pass", ""} else "warn",
        authority="live",
        enforced=True,
        reason=str(execution_quality.get("reason") or "execution quality live gate clear"),
        inputs=execution_quality,
    )
