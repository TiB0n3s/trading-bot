"""Deterministic signal preflight gates."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from services.signal_models import SignalRuntimeState


def normalize_signal_identity(raw_signal: dict[str, Any]) -> tuple[str, str]:
    symbol = str(raw_signal.get("symbol", "")).strip().upper()
    action = str(raw_signal.get("action", "")).strip().lower()
    return symbol, action


@dataclass(frozen=True)
class PreflightResult:
    allowed: bool
    rejection_category: str | None = None
    rejection_reason: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class PreflightDeps:
    now_et: Callable[[], Any]
    is_market_hours: Callable[[Any], bool]
    assert_position_exists: Callable[[str], None]
    get_position: Callable[[str], dict[str, Any] | None]
    read_cooldown: Callable[[str, str], Any]
    read_recent_sell: Callable[[str], tuple[Any, float] | None]
    adaptive_churn_reentry_allowed: Callable[..., tuple[bool, str]]
    successful_buys_today: Callable[[str], int]
    filled_buys_today: Callable[[str], int]
    cluster_exposure: Callable[[str, float], list[dict[str, Any]]]
    max_buys_per_symbol_per_day: int
    session_max_trade_count: int
    daily_loss_limit_pct: float


class PreflightService:
    def __init__(self, deps: PreflightDeps):
        self.deps = deps

    def evaluate(self, state: SignalRuntimeState) -> PreflightResult:
        symbol = state.symbol
        action = state.action
        price = float(state.raw_signal.get("price") or 0)
        account_state = state.account_state
        current_et = self.deps.now_et()
        metadata: dict[str, Any] = {"current_et": current_et}

        if not self.deps.is_market_hours(current_et):
            return PreflightResult(
                allowed=False,
                rejection_category="market_hours",
                rejection_reason=(
                    f"outside market hours: {current_et.strftime('%Y-%m-%d %H:%M:%S %Z')}"
                ),
                metadata={**metadata, "log_level": "info"},
            )

        daily_pnl_pct = account_state.get("daily_pnl_pct", 0.0)
        data_health = str(account_state.get("data_health") or "").strip().lower()
        if action == "buy" and (data_health == "degraded" or daily_pnl_pct is None):
            # Fail CLOSED: cannot evaluate the daily-loss circuit breaker when
            # broker account/position data is unavailable. Also guards the
            # comparison below against a None daily_pnl_pct.
            return PreflightResult(
                allowed=False,
                rejection_category="circuit_breaker",
                rejection_reason=(
                    "account data degraded/unavailable; failing closed on buy "
                    "(daily-loss limit cannot be evaluated)"
                ),
                metadata=metadata,
            )
        if action == "buy" and daily_pnl_pct < self.deps.daily_loss_limit_pct:
            return PreflightResult(
                allowed=False,
                rejection_category="circuit_breaker",
                rejection_reason=(
                    f"daily P&L {daily_pnl_pct:.2f}% < {self.deps.daily_loss_limit_pct:.1f}%"
                ),
                metadata=metadata,
            )

        if action == "sell":
            try:
                self.deps.assert_position_exists(symbol)
            except Exception:
                return PreflightResult(
                    allowed=False,
                    rejection_category="ghost_sell",
                    rejection_reason="no open Alpaca position",
                    metadata=metadata,
                )

        existing_position = self.deps.get_position(symbol)
        metadata["existing_position"] = existing_position
        if existing_position:
            account_state["current_symbol_position"] = existing_position

        last = self.deps.read_cooldown(symbol, action)
        if last and (current_et - last).total_seconds() < 15 * 60:
            mins_remaining = int(15 * 60 - (current_et - last).total_seconds()) // 60
            return PreflightResult(
                allowed=False,
                rejection_category="cooldown",
                rejection_reason=f"{mins_remaining}m remaining (last order {last.strftime('%H:%M')} ET)",
                metadata=metadata,
            )

        if action == "buy":
            last_sell = self.deps.read_recent_sell(symbol)
            if last_sell:
                last_sell_time, last_sell_price = last_sell
                elapsed_s = (current_et - last_sell_time).total_seconds()
                if elapsed_s < 30 * 60:
                    mins_remaining = int(30 * 60 - elapsed_s) // 60
                    return PreflightResult(
                        allowed=False,
                        rejection_category="churn_window",
                        rejection_reason=(
                            f"sold at ${last_sell_price:.2f}, "
                            f"{mins_remaining}m remaining in 30-min window"
                        ),
                        metadata=metadata,
                    )
                if last_sell_price > 0:
                    price_diff_pct = abs(price - last_sell_price) / last_sell_price * 100
                    allowed, adaptive_reason = self.deps.adaptive_churn_reentry_allowed(
                        symbol=symbol,
                        signal_price=price,
                        last_sell_price=last_sell_price,
                        account_state=account_state,
                    )
                    if allowed:
                        account_state["adaptive_churn_reentry"] = {
                            "allowed": True,
                            "price_diff_pct": round(price_diff_pct, 4),
                            "last_sell_price": last_sell_price,
                            "reason": adaptive_reason,
                        }
                    elif price_diff_pct < 0.5:
                        return PreflightResult(
                            allowed=False,
                            rejection_category="churn_price",
                            rejection_reason=(
                                f"signal ${price:.2f} within {price_diff_pct:.2f}% "
                                f"of last sell ${last_sell_price:.2f}; {adaptive_reason}"
                            ),
                            metadata=metadata,
                        )

            buys_today = self.deps.successful_buys_today(symbol)
            if buys_today >= self.deps.max_buys_per_symbol_per_day:
                return PreflightResult(
                    allowed=False,
                    rejection_category="daily_symbol_buy_limit",
                    rejection_reason=(
                        f"successful_buys_today={buys_today} >= "
                        f"limit={self.deps.max_buys_per_symbol_per_day}"
                    ),
                    metadata=metadata,
                )

            filled_entries_today = self.deps.filled_buys_today(symbol)
            if filled_entries_today >= self.deps.session_max_trade_count:
                return PreflightResult(
                    allowed=False,
                    rejection_category="session_trade_count",
                    rejection_reason=(
                        f"filled_entries_today={filled_entries_today} >= "
                        f"session_max={self.deps.session_max_trade_count}"
                    ),
                    metadata=metadata,
                )

            if existing_position:
                balance = account_state.get("balance", 0)
                position_value = existing_position["qty"] * existing_position["current_price"]
                if balance > 0:
                    exposure_pct = position_value / balance * 100
                    if exposure_pct >= 4.0:
                        return PreflightResult(
                            allowed=False,
                            rejection_category="exposure_cap",
                            rejection_reason=(
                                f"position ${position_value:.2f} = {exposure_pct:.2f}% "
                                "of balance (limit 4.0%)"
                            ),
                            metadata=metadata,
                        )

            balance = account_state.get("balance", 0)
            cluster_checks = self.deps.cluster_exposure(symbol, balance)
            metadata["cluster_checks"] = cluster_checks
            for check in cluster_checks:
                if check.get("limit_hit"):
                    return PreflightResult(
                        allowed=False,
                        rejection_category="correlation_cap",
                        rejection_reason=(
                            f"{check['cluster']} exposure {check['exposure_pct']:.2f}% "
                            f">= limit {check['limit_pct']:.2f}%"
                        ),
                        metadata=metadata,
                    )
            if cluster_checks:
                account_state["correlation_exposure"] = cluster_checks

        return PreflightResult(allowed=True, metadata=metadata)
