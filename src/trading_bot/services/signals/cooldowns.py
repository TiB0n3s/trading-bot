"""Cooldown and recent-sell persistence helpers for signal runtime."""

from __future__ import annotations

from datetime import datetime
from typing import Any


def hydrate_cooldowns(
    *,
    cooldown_repository: Any,
    last_order: dict,
    current_et: datetime,
    et_timezone: Any,
    log: Any,
    active_window_seconds: int = 15 * 60,
) -> None:
    try:
        rows = cooldown_repository.cooldown_rows()
        loaded = 0
        for symbol, action, ts_str in rows:
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = et_timezone.localize(ts)
                if (current_et - ts).total_seconds() < active_window_seconds:
                    last_order[(symbol, action)] = ts
                    loaded += 1
            except Exception as exc:
                log.warning(f"_hydrate_cooldowns: skipping {symbol}/{action}: {exc}")
        log.info(f"Hydrated {loaded} active cooldowns from cooldowns table (of {len(rows)} total)")
    except Exception as exc:
        log.error(f"_hydrate_cooldowns failed: {exc}")


def hydrate_recent_sells(
    *,
    cooldown_repository: Any,
    last_sell: dict,
    current_et: datetime,
    et_timezone: Any,
    log: Any,
    active_window_seconds: int = 30 * 60,
) -> None:
    try:
        rows = cooldown_repository.recent_sell_rows()
        loaded = 0
        for symbol, ts_str, price in rows:
            try:
                ts = datetime.fromisoformat(ts_str)
                if ts.tzinfo is None:
                    ts = et_timezone.localize(ts)
                if (current_et - ts).total_seconds() < active_window_seconds:
                    last_sell[symbol] = (ts, price)
                    loaded += 1
            except Exception as exc:
                log.warning(f"_hydrate_recent_sells: skipping {symbol}: {exc}")
        log.info(f"Hydrated {loaded} recent sells from recent_sells table (of {len(rows)} total)")
    except Exception as exc:
        log.error(f"_hydrate_recent_sells failed: {exc}")


def read_cooldown(
    *,
    symbol: str,
    action: str,
    cooldown_repository: Any,
    et_timezone: Any,
    log: Any,
) -> datetime | None:
    try:
        row = cooldown_repository.read_cooldown(symbol, action)
        if not row:
            return None
        ts = datetime.fromisoformat(row[0])
        if ts.tzinfo is None:
            ts = et_timezone.localize(ts)
        return ts
    except Exception as exc:
        log.error(f"_read_cooldown failed for {symbol}/{action}: {exc}")
        return None


def read_recent_sell(
    *,
    symbol: str,
    cooldown_repository: Any,
    et_timezone: Any,
    log: Any,
) -> tuple[datetime, Any] | None:
    try:
        row = cooldown_repository.read_recent_sell(symbol)
        if not row:
            return None
        ts = datetime.fromisoformat(row[0])
        if ts.tzinfo is None:
            ts = et_timezone.localize(ts)
        return (ts, row[1])
    except Exception as exc:
        log.error(f"_read_recent_sell failed for {symbol}: {exc}")
        return None


def write_cooldown(
    *,
    symbol: str,
    action: str,
    ts: datetime,
    cooldown_repository: Any,
    log: Any,
) -> None:
    try:
        cooldown_repository.write_cooldown(symbol, action, ts.isoformat())
    except Exception as exc:
        log.error(f"_write_cooldown failed for {symbol}/{action}: {exc}")


def write_recent_sell(
    *,
    symbol: str,
    ts: datetime,
    price: Any,
    cooldown_repository: Any,
    log: Any,
) -> None:
    try:
        cooldown_repository.write_recent_sell(symbol, ts.isoformat(), price)
    except Exception as exc:
        log.error(f"_write_recent_sell failed for {symbol}: {exc}")


def claim_cooldown(
    *,
    symbol: str,
    action: str,
    ts: datetime,
    cooldown_repository: Any,
    log: Any,
    window_seconds: int = 15 * 60,
) -> bool:
    """Atomically reserve the cooldown slot before submitting an order.

    Returns True only if this caller now owns the cooldown. Returns False if an
    active cooldown already exists OR the claim could not be performed — both
    cases fail CLOSED (do not submit), since the purpose is to prevent
    concurrent duplicate orders across gunicorn worker processes.
    """
    try:
        claimed, _existing = cooldown_repository.claim_cooldown(
            symbol, action, ts.isoformat(), window_seconds
        )
        return bool(claimed)
    except Exception as exc:
        log.error(f"_claim_cooldown failed for {symbol}/{action}: {exc}")
        return False


def release_cooldown(
    *,
    symbol: str,
    action: str,
    cooldown_repository: Any,
    log: Any,
    claimed_ts: Any = None,
) -> None:
    """Release a cooldown reservation when no order was submitted.

    When ``claimed_ts`` (the datetime passed to ``claim_cooldown``) is supplied,
    the release is conditional on the row still holding this claim's timestamp, so
    a concurrently-written newer cooldown is not clobbered.
    """
    try:
        claimed_iso = claimed_ts.isoformat() if claimed_ts is not None else None
        cooldown_repository.release_cooldown(symbol, action, claimed_iso=claimed_iso)
    except Exception as exc:
        log.error(f"_release_cooldown failed for {symbol}/{action}: {exc}")
