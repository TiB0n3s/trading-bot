"""Real signal-stage safety gates with canonical GateResult output."""

from __future__ import annotations

from typing import Any, Callable

from services.decision.trace import GateResult


def evaluate_stale_signal_gate(
    *,
    raw_signal: dict[str, Any],
    parse_stale_signal: Callable[[dict[str, Any]], tuple[bool, float | None, str]],
) -> GateResult:
    is_stale, age_seconds, stale_reason = parse_stale_signal(raw_signal)
    metadata = {"age_seconds": age_seconds}
    if is_stale:
        return GateResult(
            gate_id="stale_signal",
            layer="preflight",
            decision="block",
            authority="live",
            enforced=True,
            reason=stale_reason,
            inputs={"raw_signal": raw_signal},
            outputs={
                "rejection_category": "stale_signal",
                "metadata": metadata,
            },
        )

    updates = {}
    if age_seconds is not None:
        updates["signal_age_seconds"] = round(age_seconds, 2)
    return GateResult(
        gate_id="stale_signal",
        layer="preflight",
        decision="pass",
        authority="live",
        enforced=True,
        reason="signal freshness gate clear",
        inputs={"raw_signal": raw_signal},
        outputs={"account_state_updates": updates, "metadata": metadata},
    )


def evaluate_cash_safe_gate(
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
) -> GateResult:
    if action != "buy" or not cash_safe_mode:
        return GateResult(
            gate_id="cash_safe",
            layer="risk",
            decision="pass",
            authority="live",
            enforced=True,
            reason="cash-safe gate not applicable",
            inputs={"symbol": symbol, "action": action, "cash_safe_mode": cash_safe_mode},
        )

    if symbol not in cash_safe_symbols:
        reason = f"{symbol} not allowed in cash_safe symbols {sorted(cash_safe_symbols)}"
        return GateResult(
            gate_id="cash_safe",
            layer="risk",
            decision="block",
            authority="live",
            enforced=True,
            reason=reason,
            inputs={"symbol": symbol, "cash_safe_symbols": sorted(cash_safe_symbols)},
            outputs={
                "rejection_category": "cash_safe_symbol",
                "metadata": {"cash_safe_symbols": sorted(cash_safe_symbols)},
            },
        )

    open_count = account_state.get("open_position_count", 0)
    if open_count >= max_open_positions:
        reason = f"open_position_count={open_count} >= cash_safe max {max_open_positions}"
        metadata = {
            "open_position_count": open_count,
            "max_open_positions": max_open_positions,
        }
        return GateResult(
            gate_id="cash_safe",
            layer="risk",
            decision="block",
            authority="live",
            enforced=True,
            reason=reason,
            inputs={"symbol": symbol, **metadata},
            outputs={
                "rejection_category": "cash_safe_position_limit",
                "metadata": metadata,
            },
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
        metadata = {
            "buys_today": buys_today,
            "max_buys_per_symbol": max_new_buys_per_symbol_per_day,
        }
        return GateResult(
            gate_id="cash_safe",
            layer="risk",
            decision="block",
            authority="live",
            enforced=True,
            reason=reason,
            inputs={"symbol": symbol, **metadata},
            outputs={
                "rejection_category": "cash_safe_daily_symbol_limit",
                "metadata": metadata,
            },
        )

    return GateResult(
        gate_id="cash_safe",
        layer="risk",
        decision="pass",
        authority="live",
        enforced=True,
        reason="cash-safe gate clear",
        inputs={
            "symbol": symbol,
            "cash_safe_mode": cash_safe_mode,
            "open_position_count": open_count,
            "buys_today": buys_today,
        },
    )


def evaluate_symbol_override_gate(
    *,
    symbol: str,
    action: str,
    symbol_override_block: Callable[[str, str], str | None],
) -> GateResult:
    override_reason = symbol_override_block(symbol, action)
    if not override_reason:
        return GateResult(
            gate_id="symbol_override",
            layer="preflight",
            decision="pass",
            authority="live",
            enforced=True,
            reason="symbol override gate clear",
            inputs={"symbol": symbol, "action": action},
        )

    return GateResult(
        gate_id="symbol_override",
        layer="preflight",
        decision="block",
        authority="live",
        enforced=True,
        reason=override_reason,
        inputs={"symbol": symbol, "action": action},
        outputs={
            "rejection_category": "symbol_override",
            "metadata": {"override_reason": override_reason},
        },
    )
