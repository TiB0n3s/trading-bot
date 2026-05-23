#!/usr/bin/env python3
"""
Order policy helpers.

Read-only helpers for order-adjacent policy decisions.

This module does not submit, cancel, approve, reject, or size orders by itself.
It prepares the path for moving execution-policy logic out of broker.py/app.py.
"""

from __future__ import annotations

from typing import Any


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def safe_int(value: Any, default: int = 0) -> int:
    try:
        return int(float(value))
    except Exception:
        return default


def calculate_buy_qty(
    balance: float,
    position_size_pct: float,
    current_price: float,
    risk_level: str | None = None,
) -> dict[str, Any]:
    """
    Calculate buy quantity using the same basic sizing concept as broker.py.

    Returns a policy dict instead of placing an order.
    """
    balance = safe_float(balance)
    position_size_pct = safe_float(position_size_pct)
    current_price = safe_float(current_price)

    if balance <= 0:
        return {
            "allowed": False,
            "qty": 0,
            "risk_amount": 0.0,
            "reason": "balance <= 0",
        }

    if position_size_pct <= 0:
        return {
            "allowed": False,
            "qty": 0,
            "risk_amount": 0.0,
            "reason": "position_size_pct <= 0",
        }

    if current_price <= 0:
        return {
            "allowed": False,
            "qty": 0,
            "risk_amount": 0.0,
            "reason": "current_price <= 0",
        }

    risk_amount = balance * (position_size_pct / 100.0)
    raw_qty = int(risk_amount / current_price)
    qty = raw_qty

    risk_adjustment = None
    if risk_level == "very_high" and qty >= 2:
        qty = qty // 2
        risk_adjustment = f"very_high risk_level halved qty {raw_qty} -> {qty}"

    if qty < 1:
        return {
            "allowed": False,
            "qty": 0,
            "raw_qty": raw_qty,
            "risk_amount": round(risk_amount, 2),
            "reason": "qty rounds below 1",
            "risk_adjustment": risk_adjustment,
        }

    return {
        "allowed": True,
        "qty": qty,
        "raw_qty": raw_qty,
        "risk_amount": round(risk_amount, 2),
        "reason": "buy quantity allowed",
        "risk_adjustment": risk_adjustment,
    }


def calculate_bracket_prices(
    side: str,
    current_price: float,
    stop_loss_pct: float,
    take_profit_pct: float,
) -> dict[str, Any]:
    """
    Calculate stop/take-profit prices for an order policy preview.

    For buys:
      stop below current price
      take-profit above current price

    For sells:
      fields are not meaningful for market exits, but this mirrors legacy math.
    """
    side = str(side or "").lower()
    current_price = safe_float(current_price)
    stop_loss_pct = safe_float(stop_loss_pct)
    take_profit_pct = safe_float(take_profit_pct)

    if current_price <= 0:
        return {
            "allowed": False,
            "reason": "current_price <= 0",
            "stop_price": None,
            "take_profit_price": None,
        }

    if side == "buy":
        stop_price = round(current_price * (1 - stop_loss_pct / 100.0), 2)
        take_price = round(current_price * (1 + take_profit_pct / 100.0), 2)
    elif side == "sell":
        stop_price = round(current_price * (1 + stop_loss_pct / 100.0), 2)
        take_price = round(current_price * (1 - take_profit_pct / 100.0), 2)
    else:
        return {
            "allowed": False,
            "reason": f"unsupported side={side}",
            "stop_price": None,
            "take_profit_price": None,
        }

    return {
        "allowed": True,
        "side": side,
        "current_price": current_price,
        "stop_price": stop_price,
        "take_profit_price": take_price,
        "stop_loss_pct": stop_loss_pct,
        "take_profit_pct": take_profit_pct,
        "reason": "bracket prices calculated",
    }


def cash_order_cap_check(
    qty: int,
    current_price: float,
    max_order_dollars: float,
) -> dict[str, Any]:
    """Return whether a cash/live order notional is within configured cap."""
    qty = safe_int(qty)
    current_price = safe_float(current_price)
    max_order_dollars = safe_float(max_order_dollars)

    notional = qty * current_price

    if qty <= 0:
        return {
            "allowed": False,
            "notional": round(notional, 2),
            "reason": "qty <= 0",
        }

    if current_price <= 0:
        return {
            "allowed": False,
            "notional": round(notional, 2),
            "reason": "current_price <= 0",
        }

    if max_order_dollars <= 0:
        return {
            "allowed": False,
            "notional": round(notional, 2),
            "reason": "max_order_dollars <= 0",
        }

    if notional > max_order_dollars:
        return {
            "allowed": False,
            "notional": round(notional, 2),
            "max_order_dollars": round(max_order_dollars, 2),
            "reason": "order notional exceeds max_order_dollars",
        }

    return {
        "allowed": True,
        "notional": round(notional, 2),
        "max_order_dollars": round(max_order_dollars, 2),
        "reason": "order notional within cap",
    }
