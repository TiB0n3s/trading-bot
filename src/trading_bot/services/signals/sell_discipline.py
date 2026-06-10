"""Sell-continuation discipline helpers."""

from __future__ import annotations

import os
from typing import Any, Callable


def safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def sell_continuation_delay_reason(
    account_state: dict[str, Any] | None,
    trend: dict[str, Any] | None,
    unrealized_pct: Any,
    *,
    env_float: Callable[[str, float], float],
    environ: Any = os.environ,
) -> str | None:
    """
    Return a rejection reason when a normal webhook SELL looks early.

    This protects against indicator-alert noise cutting a position while the
    latest session tape still supports continuation. Hard loss exits and broker
    brackets do not use this path.
    """
    enabled = str(environ.get("SELL_CONTINUATION_CHECK_ENABLED", "true")).strip().lower()
    if enabled not in ("1", "true", "yes", "on"):
        return None

    unrealized = safe_float(unrealized_pct)
    if unrealized is None:
        return None

    hard_loss_floor = env_float("SELL_CONTINUATION_HARD_LOSS_FLOOR_PCT", -0.75)
    if unrealized <= hard_loss_floor:
        return None

    session = (account_state or {}).get("session_momentum") or {}
    trend = trend or {}

    session_score = safe_float(session.get("trend_score"))
    session_5m = safe_float(session.get("momentum_5m_pct"))
    session_15m = safe_float(session.get("momentum_15m_pct"))
    session_30m = safe_float(session.get("momentum_30m_pct"))
    vwap_dist = safe_float(session.get("distance_from_vwap_pct"))
    session_label = session.get("trend_label")

    if session_5m is not None and session_5m <= env_float(
        "SELL_CONTINUATION_MAX_5M_DROP_PCT", -0.20
    ):
        return None
    if session_15m is not None and session_15m <= env_float(
        "SELL_CONTINUATION_MAX_15M_DROP_PCT", -0.10
    ):
        return None

    supports = []
    min_momentum = env_float("SELL_CONTINUATION_MIN_MOMENTUM_PCT", 0.15)
    min_vwap_dist = env_float("SELL_CONTINUATION_MIN_VWAP_DIST_PCT", 0.10)
    min_session_score = env_float("SELL_CONTINUATION_MIN_SESSION_SCORE", 2.0)

    if session_15m is not None and session_15m >= min_momentum:
        supports.append(f"15m={session_15m:.3f}%")
    if session_30m is not None and session_30m >= min_momentum:
        supports.append(f"30m={session_30m:.3f}%")
    if vwap_dist is not None and vwap_dist >= min_vwap_dist:
        supports.append(f"vwap_dist={vwap_dist:.3f}%")
    if session_score is not None and session_score >= min_session_score:
        supports.append(f"session_score={session_score:.1f}")

    direction = trend.get("direction")
    strength = trend.get("strength")
    consecutive_count = int(trend.get("consecutive_count") or 0)
    strong_bearish_pressure = (
        direction == "bearish" and strength == "confirmed" and consecutive_count >= 3
    )

    required_support_count = int(environ.get("SELL_CONTINUATION_MIN_SUPPORTS", "2"))
    if len(supports) >= required_support_count and not strong_bearish_pressure:
        return (
            "sell continuation check: "
            f"unrealized={unrealized:.2f}% "
            f"session_label={session_label} "
            f"trend={direction}/{strength} count={consecutive_count}; "
            f"supports={', '.join(supports)}"
        )

    return None
