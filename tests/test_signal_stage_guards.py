#!/usr/bin/env python3
"""Unit tests for signal stage guard seams."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.signal_stage_guards import (
    apply_symbol_overrides,
    check_cash_safe_gates,
    check_stale_signal,
)


def test_stale_signal_returns_normalized_rejection():
    result = check_stale_signal(
        raw_signal={"symbol": "AAPL"},
        parse_stale_signal=lambda _: (True, 121.3, "too old"),
    )

    assert result.rejected is True
    assert result.approval.category == "stale_signal"
    assert result.approval.reason == "too old"
    assert result.approval.metadata["age_seconds"] == 121.3


def test_fresh_signal_updates_age_without_rejection():
    result = check_stale_signal(
        raw_signal={"symbol": "AAPL"},
        parse_stale_signal=lambda _: (False, 4.567, "ok"),
    )

    assert result.rejected is False
    assert result.account_state_updates == {"signal_age_seconds": 4.57}


def test_cash_safe_symbol_guard_rejects_unapproved_symbol():
    result = check_cash_safe_gates(
        symbol="TSLA",
        action="buy",
        account_state={"open_position_count": 0},
        cash_safe_mode=True,
        cash_safe_symbols={"AAPL"},
        max_open_positions=2,
        max_new_buys_per_symbol_per_day=1,
        cash_safe_buys_today=lambda _: 0,
    )

    assert result.rejected is True
    assert result.approval.category == "cash_safe_symbol"


def test_cash_safe_daily_symbol_limit_rejects_at_limit():
    result = check_cash_safe_gates(
        symbol="AAPL",
        action="buy",
        account_state={"open_position_count": 0},
        cash_safe_mode=True,
        cash_safe_symbols={"AAPL"},
        max_open_positions=2,
        max_new_buys_per_symbol_per_day=1,
        cash_safe_buys_today=lambda _: 1,
    )

    assert result.rejected is True
    assert result.approval.category == "cash_safe_daily_symbol_limit"


def test_symbol_override_rejects_with_metadata():
    result = apply_symbol_overrides(
        symbol="AAPL",
        action="buy",
        symbol_override_block=lambda symbol, action: f"{symbol} {action} blocked",
    )

    assert result.rejected is True
    assert result.approval.category == "symbol_override"
    assert result.metadata == {"override_reason": "AAPL buy blocked"}
