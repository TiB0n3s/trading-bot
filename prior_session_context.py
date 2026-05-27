#!/usr/bin/env python3
"""Read-only prior-session context for entry intelligence."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection
from market_time import is_trading_day, now_et


def _parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def _trading_days_between(start: date, end: date) -> int | None:
    if start > end:
        return None
    days = 0
    current = start + timedelta(days=1)
    while current <= end:
        if is_trading_day(current):
            days += 1
        current += timedelta(days=1)
    return days


def prior_session_context(symbol: str, db_path: Path | str = DB_PATH) -> dict[str, Any] | None:
    """
    Return the most recent strong_day_participation row for a symbol.

    Read-only. Intended for BUY signal context only; missing data returns None.
    """
    symbol = (symbol or "").upper().strip()
    if not symbol:
        return None

    try:
        with get_connection(db_path) as con:
            table = con.execute(
                """
                SELECT 1 FROM sqlite_master
                WHERE type = 'table' AND name = 'strong_day_participation'
                """
            ).fetchone()
            if not table:
                return None

            row = con.execute(
                """
                SELECT market_date,
                       session_return_pct,
                       primary_status,
                       buy_signal_count,
                       approved_buy_count,
                       rejected_buy_count,
                       sell_signal_count,
                       auto_buy_candidate_count,
                       auto_buy_strong_count
                FROM strong_day_participation
                WHERE symbol = ?
                ORDER BY market_date DESC, id DESC
                LIMIT 1
                """,
                (symbol,),
            ).fetchone()
    except Exception:
        return None

    if not row:
        return None

    market_date = _parse_date(row["market_date"])
    today = now_et().date()
    age_days = _trading_days_between(market_date, today) if market_date else None
    signal_count = int(
        (row["buy_signal_count"] or 0)
        + (row["sell_signal_count"] or 0)
        + (row["auto_buy_candidate_count"] or 0)
    )
    participated = bool(
        (row["approved_buy_count"] or 0)
        or (row["rejected_buy_count"] or 0)
        or (row["auto_buy_candidate_count"] or 0)
    )

    return {
        "market_date": row["market_date"],
        "session_return_pct": row["session_return_pct"],
        "participated": participated,
        "signal_count": signal_count,
        "participation_quality": row["primary_status"],
        "session_age_days": age_days,
    }
