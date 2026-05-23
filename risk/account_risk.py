#!/usr/bin/env python3
"""
Account risk helpers.

Read-only helpers for account/position risk summaries.

This module does not approve, reject, size, or place orders.
It is the first safe extraction step away from the monolithic app.py.
"""

from __future__ import annotations

from typing import Any


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def summarize_account(account: dict[str, Any] | None) -> dict[str, Any]:
    """Normalize a broker account dict into a consistent read-only summary."""
    account = account or {}

    return {
        "balance": safe_float(account.get("balance")),
        "portfolio_value": safe_float(account.get("portfolio_value")),
        "buying_power": safe_float(account.get("buying_power")),
        "status": account.get("status"),
    }


def summarize_positions(positions: list[dict[str, Any]] | None) -> dict[str, Any]:
    """Return aggregate stats for a list of position dicts."""
    positions = positions or []

    total_market_value = 0.0
    total_unrealized_pl = 0.0
    long_count = 0
    short_count = 0

    for p in positions:
        qty = safe_float(p.get("qty"))
        market_value = safe_float(
            p.get("market_value", p.get("value", p.get("current_value", 0.0)))
        )
        unrealized = safe_float(p.get("unrealized_pl"))

        total_market_value += abs(market_value)
        total_unrealized_pl += unrealized

        if qty > 0:
            long_count += 1
        elif qty < 0:
            short_count += 1

    return {
        "position_count": len(positions),
        "long_count": long_count,
        "short_count": short_count,
        "total_market_value": round(total_market_value, 2),
        "total_unrealized_pl": round(total_unrealized_pl, 2),
    }


def symbol_exposure_pct(position_value: float, balance: float) -> float:
    """Return position exposure as percent of account balance/cash."""
    balance = safe_float(balance)
    position_value = safe_float(position_value)

    if balance <= 0:
        return 0.0

    return round(position_value / balance * 100, 4)


def exposure_cap_hit(position_value: float, balance: float, cap_pct: float = 4.0) -> bool:
    """Return True if a symbol's exposure is at or above the configured cap."""
    return symbol_exposure_pct(position_value, balance) >= cap_pct


def account_risk_snapshot(
    account: dict[str, Any] | None,
    positions: list[dict[str, Any]] | None,
    daily_pnl_pct: float | None = None,
    max_positions: int = 8,
) -> dict[str, Any]:
    """Return a compact read-only account risk snapshot."""
    acct = summarize_account(account)
    pos = summarize_positions(positions)

    open_count = pos["position_count"]

    return {
        "account": acct,
        "positions": pos,
        "daily_pnl_pct": safe_float(daily_pnl_pct),
        "max_positions": max_positions,
        "position_slots_used": open_count,
        "position_slots_remaining": max(0, max_positions - open_count),
        "max_positions_hit": open_count >= max_positions,
    }
