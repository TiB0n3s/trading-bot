"""Behavior-preserving legacy signal stage helpers.

These helpers are migration seams for draining app.py. They decide whether a
stage should continue or return a normalized rejection, but they do not write
audit rows, update webhook status, or submit orders.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from services.approval_service import ApprovalDecision, deterministic_rejection


@dataclass(frozen=True)
class LegacyStageDecision:
    rejected: bool = False
    approval: ApprovalDecision | None = None
    account_state_updates: dict[str, Any] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)


LEGACY_STAGE_CONTINUE = LegacyStageDecision()


def check_stale_signal(
    *,
    raw_signal: dict[str, Any],
    parse_stale_signal: Callable[[dict[str, Any]], tuple[bool, float | None, str]],
) -> LegacyStageDecision:
    is_stale, age_seconds, stale_reason = parse_stale_signal(raw_signal)
    if is_stale:
        return LegacyStageDecision(
            rejected=True,
            approval=deterministic_rejection(
                category="stale_signal",
                reason=stale_reason,
                metadata={"age_seconds": age_seconds},
            ),
            metadata={"age_seconds": age_seconds},
        )

    updates = {}
    if age_seconds is not None:
        updates["signal_age_seconds"] = round(age_seconds, 2)
    return LegacyStageDecision(account_state_updates=updates)


def check_cash_safe_gates(
    *,
    symbol: str,
    action: str,
    account_state: dict[str, Any],
    cash_safe_mode: bool,
    cash_safe_symbols: set[str],
    max_open_positions: int,
    max_new_buys_per_symbol_per_day: int,
    cash_safe_buys_today: Callable[[str], int],
    log: Any = None,
) -> LegacyStageDecision:
    if action != "buy" or not cash_safe_mode:
        return LEGACY_STAGE_CONTINUE

    if symbol not in cash_safe_symbols:
        reason = f"{symbol} not allowed in cash_safe symbols {sorted(cash_safe_symbols)}"
        return LegacyStageDecision(
            rejected=True,
            approval=deterministic_rejection(
                category="cash_safe_symbol",
                reason=reason,
                metadata={"cash_safe_symbols": sorted(cash_safe_symbols)},
            ),
        )

    open_count = account_state.get("open_position_count", 0)
    if open_count >= max_open_positions:
        reason = (
            f"open_position_count={open_count} >= cash_safe max "
            f"{max_open_positions}"
        )
        return LegacyStageDecision(
            rejected=True,
            approval=deterministic_rejection(
                category="cash_safe_position_limit",
                reason=reason,
                metadata={
                    "open_position_count": open_count,
                    "max_open_positions": max_open_positions,
                },
            ),
        )

    try:
        buys_today = cash_safe_buys_today(symbol)
    except Exception as exc:
        if log:
            log.error(f"Cash-safe daily buy check failed for {symbol}: {exc}")
        buys_today = 999

    if buys_today >= max_new_buys_per_symbol_per_day:
        reason = (
            f"buys_today={buys_today} >= cash_safe per-symbol daily max "
            f"{max_new_buys_per_symbol_per_day}"
        )
        return LegacyStageDecision(
            rejected=True,
            approval=deterministic_rejection(
                category="cash_safe_daily_symbol_limit",
                reason=reason,
                metadata={
                    "buys_today": buys_today,
                    "max_buys_per_symbol": max_new_buys_per_symbol_per_day,
                },
            ),
        )

    return LEGACY_STAGE_CONTINUE


def apply_symbol_overrides(
    *,
    symbol: str,
    action: str,
    symbol_override_block: Callable[[str, str], str | None],
) -> LegacyStageDecision:
    override_reason = symbol_override_block(symbol, action)
    if not override_reason:
        return LEGACY_STAGE_CONTINUE

    return LegacyStageDecision(
        rejected=True,
        approval=deterministic_rejection(
            category="symbol_override",
            reason=override_reason,
        ),
        metadata={"override_reason": override_reason},
    )
