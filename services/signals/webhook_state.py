"""Webhook dedupe and same-day trade count helpers."""

from __future__ import annotations

from typing import Any


def webhook_dedupe_key(symbol: Any, action: Any, price: Any) -> str:
    """Build a loose duplicate key for near-identical TradingView alerts."""
    try:
        price_key = f"{float(price):.2f}"
    except Exception:
        price_key = str(price)
    return f"{symbol}:{action}:{price_key}"


def is_duplicate_webhook(
    *,
    symbol: Any,
    action: Any,
    price: Any,
    cooldown_repository: Any,
    dedupe_seconds: int,
    log: Any,
) -> bool:
    """Return True if the same symbol/action/rounded-price arrived recently."""
    try:
        key = webhook_dedupe_key(symbol, action, price)
        return cooldown_repository.recent_webhook_seen(
            key,
            symbol,
            action,
            price,
            dedupe_seconds,
        )
    except Exception as exc:
        log.error(f"_is_duplicate_webhook failed for {symbol}/{action}: {exc}")
        return False


def successful_buys_today(*, symbol: Any, trades_repository: Any, log: Any) -> int:
    try:
        return trades_repository.successful_buys_today(symbol)
    except Exception as exc:
        log.error(f"_successful_buys_today failed for {symbol}: {exc}")
        return 0


def filled_buys_today(*, symbol: Any, trades_repository: Any, log: Any) -> int:
    try:
        return trades_repository.filled_buys_today(symbol)
    except Exception as exc:
        log.error(f"_filled_buys_today failed for {symbol}: {exc}")
        return 0
