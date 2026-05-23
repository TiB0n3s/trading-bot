#!/usr/bin/env python3
"""
Exposure helpers.

Read-only helpers for per-symbol and correlation-cluster exposure checks.

This module does not approve, reject, size, or place orders.
It is a safe extraction step away from app.py.
"""

from __future__ import annotations

from typing import Any


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def position_market_value(position: dict[str, Any] | None) -> float:
    """Return a best-effort market value for a position dict."""
    position = position or {}

    if "market_value" in position:
        return abs(safe_float(position.get("market_value")))

    qty = safe_float(position.get("qty"))
    current_price = safe_float(position.get("current_price"))

    return abs(qty * current_price)


def symbol_exposure_pct(
    position: dict[str, Any] | None,
    balance: float,
) -> float:
    """Return a single position's exposure as percent of balance."""
    balance = safe_float(balance)
    if balance <= 0:
        return 0.0

    value = position_market_value(position)
    return round(value / balance * 100, 4)


def symbol_exposure_cap_hit(
    position: dict[str, Any] | None,
    balance: float,
    cap_pct: float = 4.0,
) -> bool:
    """Return True if a symbol's position exposure is at/above cap."""
    return symbol_exposure_pct(position, balance) >= cap_pct


def positions_by_symbol(positions: list[dict[str, Any]] | None) -> dict[str, dict[str, Any]]:
    """Return positions keyed by symbol."""
    out = {}
    for p in positions or []:
        symbol = str(p.get("symbol") or "").upper()
        if symbol:
            out[symbol] = p
    return out


def cluster_exposure(
    symbol: str,
    positions: list[dict[str, Any]] | None,
    balance: float,
    correlation_clusters: dict[str, set[str]] | dict[str, list[str]],
    cluster_limits: dict[str, float],
) -> list[dict[str, Any]]:
    """
    Return cluster exposure details for every cluster containing `symbol`.

    Example result:
    [
      {
        "cluster": "mega_cap_tech",
        "members": ["AAPL", "MSFT", "QQQ"],
        "current_value": 12345.67,
        "exposure_pct": 12.34,
        "limit_pct": 15.0,
        "limit_hit": false
      }
    ]
    """
    symbol = symbol.upper()
    balance = safe_float(balance)

    if balance <= 0:
        return []

    by_symbol = positions_by_symbol(positions)
    results = []

    for cluster_name, members_raw in correlation_clusters.items():
        members = {str(m).upper() for m in members_raw}

        if symbol not in members:
            continue

        cluster_value = 0.0

        for member in members:
            position = by_symbol.get(member)
            if position:
                cluster_value += position_market_value(position)

        exposure_pct = round(cluster_value / balance * 100, 4)
        limit_pct = safe_float(cluster_limits.get(cluster_name), 100.0)

        results.append({
            "cluster": cluster_name,
            "members": sorted(members),
            "current_value": round(cluster_value, 2),
            "exposure_pct": exposure_pct,
            "limit_pct": limit_pct,
            "limit_hit": exposure_pct >= limit_pct,
        })

    return results


def any_cluster_limit_hit(cluster_checks: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Return the first cluster check that hit its limit, else None."""
    for check in cluster_checks or []:
        if check.get("limit_hit"):
            return check
    return None
