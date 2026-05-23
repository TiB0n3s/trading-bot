#!/usr/bin/env python3
"""
Live/cash-mode guard helpers.

Read-only helpers for describing execution-mode safety policy.

This module does not place orders and does not change live behavior.
It prepares the path for moving live/cash safety checks out of app.py/broker.py.
"""

from __future__ import annotations

from typing import Any


VALID_EXECUTION_MODES = {"paper", "cash_safe", "cash_full", "dry_run"}


def normalize_execution_mode(value: Any) -> str:
    mode = str(value or "paper").strip().lower()
    return mode if mode in VALID_EXECUTION_MODES else "paper"


def parse_bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default

    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def parse_symbol_csv(value: Any) -> set[str]:
    return {
        s.strip().upper()
        for s in str(value or "").split(",")
        if s.strip()
    }


def is_cash_mode(execution_mode: str) -> bool:
    return normalize_execution_mode(execution_mode) in {"cash_safe", "cash_full"}


def is_cash_safe_mode(execution_mode: str) -> bool:
    return normalize_execution_mode(execution_mode) == "cash_safe"


def live_guard_policy(env: dict[str, Any]) -> dict[str, Any]:
    """Return a normalized live/cash guard policy from an env-like dict."""
    execution_mode = normalize_execution_mode(env.get("EXECUTION_MODE", "paper"))
    live_trading_enabled = parse_bool(env.get("LIVE_TRADING_ENABLED"), False)

    cash_safe_symbols = parse_symbol_csv(
        env.get("CASH_SAFE_SYMBOLS", "SPY,QQQ,AAPL,MSFT,NVDA")
    )

    try:
        cash_safe_max_open_positions = int(env.get("CASH_SAFE_MAX_OPEN_POSITIONS", 3))
    except Exception:
        cash_safe_max_open_positions = 3

    try:
        cash_safe_max_new_buys_per_symbol_per_day = int(
            env.get("CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY", 1)
        )
    except Exception:
        cash_safe_max_new_buys_per_symbol_per_day = 1

    try:
        max_live_order_dollars = float(env.get("MAX_LIVE_ORDER_DOLLARS", 500))
    except Exception:
        max_live_order_dollars = 500.0

    try:
        cash_safe_max_order_dollars = float(env.get("CASH_SAFE_MAX_ORDER_DOLLARS", 500))
    except Exception:
        cash_safe_max_order_dollars = 500.0

    return {
        "execution_mode": execution_mode,
        "live_trading_enabled": live_trading_enabled,
        "cash_mode": is_cash_mode(execution_mode),
        "cash_safe_mode": is_cash_safe_mode(execution_mode),
        "cash_safe_symbols": sorted(cash_safe_symbols),
        "cash_safe_max_open_positions": cash_safe_max_open_positions,
        "cash_safe_max_new_buys_per_symbol_per_day": cash_safe_max_new_buys_per_symbol_per_day,
        "max_live_order_dollars": max_live_order_dollars,
        "cash_safe_max_order_dollars": cash_safe_max_order_dollars,
    }


def live_order_allowed(policy: dict[str, Any]) -> tuple[bool, str]:
    """Return whether live/cash order submission is allowed by mode-level guard."""
    execution_mode = normalize_execution_mode(policy.get("execution_mode"))

    if execution_mode in {"paper", "dry_run"}:
        return True, f"execution_mode={execution_mode}"

    if is_cash_mode(execution_mode) and not policy.get("live_trading_enabled"):
        return False, (
            f"execution_mode={execution_mode} but LIVE_TRADING_ENABLED is false"
        )

    return True, f"execution_mode={execution_mode}; live trading enabled"
