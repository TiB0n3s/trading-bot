#!/usr/bin/env python3
"""
Session-aware intraday momentum tracker.

Observe-only first pass:
- Fetches 1-minute bars from Alpaca IEX.
- Computes session return, 5m/15m/30m momentum, VWAP distance, and trend label.
- Stores latest per-symbol state in trades.db table session_momentum.
- Does not place orders or change trading behavior.

Usage:
  python3 session_momentum.py --symbol NVDA
  python3 session_momentum.py --all
"""

from __future__ import annotations

import argparse
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from alpaca_trade_api.rest import REST

from db import get_connection
from runtime_config import get_alpaca_base_url
from symbols_config import APPROVED_SYMBOLS_LIST

logger = logging.getLogger("session_momentum")

DB_PATH = Path(__file__).resolve().parent / "trades.db"

MIN_BARS = 5
LOOKBACK_MINUTES = 240


def init_session_momentum_table() -> None:
    with get_connection(DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS session_momentum (
                symbol TEXT PRIMARY KEY,
                updated_at TEXT NOT NULL,
                bar_count INTEGER,
                session_open_price REAL,
                latest_price REAL,
                session_return_pct REAL,
                momentum_5m_pct REAL,
                momentum_15m_pct REAL,
                momentum_30m_pct REAL,
                vwap REAL,
                distance_from_vwap_pct REAL,
                trend_label TEXT,
                trend_score INTEGER,
                reason TEXT
            )
            """
        )


def _pct_change(start: float | None, end: float | None) -> float | None:
    if start is None or end is None:
        return None
    if start <= 0:
        return None
    return (end - start) / start * 100.0


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def _bar_close(bar: Any) -> float | None:
    return _safe_float(getattr(bar, "c", None))


def _bar_volume(bar: Any) -> float:
    return _safe_float(getattr(bar, "v", None)) or 0.0


def _compute_vwap(bars: list[Any]) -> float | None:
    total_pv = 0.0
    total_v = 0.0

    for bar in bars:
        close = _bar_close(bar)
        volume = _bar_volume(bar)
        if close is None or volume <= 0:
            continue
        total_pv += close * volume
        total_v += volume

    if total_v <= 0:
        return None

    return total_pv / total_v


def _window_return(bars: list[Any], window: int) -> float | None:
    if len(bars) < 2:
        return None

    scoped = bars[-window:] if len(bars) >= window else bars
    first = _bar_close(scoped[0])
    last = _bar_close(scoped[-1])
    return _pct_change(first, last)


def classify_session_momentum(
    *,
    session_return_pct: float | None,
    momentum_5m_pct: float | None,
    momentum_15m_pct: float | None,
    momentum_30m_pct: float | None,
    distance_from_vwap_pct: float | None,
    bar_count: int,
) -> dict[str, Any]:
    if bar_count < MIN_BARS:
        return {
            "trend_label": "insufficient_data",
            "trend_score": 0,
            "reason": f"bar_count={bar_count} < {MIN_BARS}",
        }

    score = 0
    reasons = []

    def add(condition: bool, points: int, reason: str) -> None:
        nonlocal score
        if condition:
            score += points
            reasons.append(reason)

    sr = session_return_pct or 0.0
    m5 = momentum_5m_pct or 0.0
    m15 = momentum_15m_pct or 0.0
    m30 = momentum_30m_pct or 0.0
    vwap_dist = distance_from_vwap_pct or 0.0

    add(sr > 0.50, 2, "session_return_positive")
    add(sr < -0.50, -2, "session_return_negative")

    add(m5 > 0.10, 1, "5m_rising")
    add(m5 < -0.10, -1, "5m_falling")

    add(m15 > 0.20, 2, "15m_rising")
    add(m15 < -0.20, -2, "15m_falling")

    add(m30 > 0.35, 2, "30m_rising")
    add(m30 < -0.35, -2, "30m_falling")

    add(vwap_dist > 0.15, 1, "above_vwap")
    add(vwap_dist < -0.15, -1, "below_vwap")

    if score >= 6:
        label = "strong_uptrend"
    elif score >= 3:
        label = "developing_uptrend"
    elif score >= 1 and sr < 0 and m5 > 0 and m15 > 0:
        label = "reversal_attempt"
    elif score <= -5:
        label = "downtrend"
    elif score <= -2:
        label = "fading"
    else:
        label = "rangebound"

    return {
        "trend_label": label,
        "trend_score": score,
        "reason": ",".join(reasons) if reasons else "mixed_or_flat",
    }


def build_session_momentum(api: REST, symbol: str) -> dict[str, Any]:
    symbol = symbol.upper()
    start = (datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MINUTES)).isoformat()

    bars = list(api.get_bars(symbol, "1Min", start=start, feed="iex"))
    bars = [b for b in bars if _bar_close(b) is not None]

    if not bars:
        now = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        return {
            "symbol": symbol,
            "updated_at": now,
            "bar_count": 0,
            "session_open_price": None,
            "latest_price": None,
            "session_return_pct": None,
            "momentum_5m_pct": None,
            "momentum_15m_pct": None,
            "momentum_30m_pct": None,
            "vwap": None,
            "distance_from_vwap_pct": None,
            "trend_label": "insufficient_data",
            "trend_score": 0,
            "reason": f"no 1Min IEX bars returned in last {LOOKBACK_MINUTES} minutes; likely pre-market, closed market, or data unavailable",
        }

    session_open = _bar_close(bars[0])
    latest = _bar_close(bars[-1])
    session_return = _pct_change(session_open, latest)

    momentum_5m = _window_return(bars, 5)
    momentum_15m = _window_return(bars, 15)
    momentum_30m = _window_return(bars, 30)

    vwap = _compute_vwap(bars)
    distance_from_vwap = _pct_change(vwap, latest) if vwap and latest else None

    classification = classify_session_momentum(
        session_return_pct=session_return,
        momentum_5m_pct=momentum_5m,
        momentum_15m_pct=momentum_15m,
        momentum_30m_pct=momentum_30m,
        distance_from_vwap_pct=distance_from_vwap,
        bar_count=len(bars),
    )

    return {
        "symbol": symbol,
        "updated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "bar_count": len(bars),
        "session_open_price": round(session_open, 4) if session_open is not None else None,
        "latest_price": round(latest, 4) if latest is not None else None,
        "session_return_pct": round(session_return, 3) if session_return is not None else None,
        "momentum_5m_pct": round(momentum_5m, 3) if momentum_5m is not None else None,
        "momentum_15m_pct": round(momentum_15m, 3) if momentum_15m is not None else None,
        "momentum_30m_pct": round(momentum_30m, 3) if momentum_30m is not None else None,
        "vwap": round(vwap, 4) if vwap is not None else None,
        "distance_from_vwap_pct": round(distance_from_vwap, 3) if distance_from_vwap is not None else None,
        "trend_label": classification["trend_label"],
        "trend_score": classification["trend_score"],
        "reason": classification["reason"],
    }


def upsert_session_momentum(row: dict[str, Any]) -> None:
    with get_connection(DB_PATH) as con:
        con.execute(
            """
            INSERT INTO session_momentum (
                symbol,
                updated_at,
                bar_count,
                session_open_price,
                latest_price,
                session_return_pct,
                momentum_5m_pct,
                momentum_15m_pct,
                momentum_30m_pct,
                vwap,
                distance_from_vwap_pct,
                trend_label,
                trend_score,
                reason
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                updated_at=excluded.updated_at,
                bar_count=excluded.bar_count,
                session_open_price=excluded.session_open_price,
                latest_price=excluded.latest_price,
                session_return_pct=excluded.session_return_pct,
                momentum_5m_pct=excluded.momentum_5m_pct,
                momentum_15m_pct=excluded.momentum_15m_pct,
                momentum_30m_pct=excluded.momentum_30m_pct,
                vwap=excluded.vwap,
                distance_from_vwap_pct=excluded.distance_from_vwap_pct,
                trend_label=excluded.trend_label,
                trend_score=excluded.trend_score,
                reason=excluded.reason
            """,
            (
                row.get("symbol"),
                row.get("updated_at"),
                row.get("bar_count"),
                row.get("session_open_price"),
                row.get("latest_price"),
                row.get("session_return_pct"),
                row.get("momentum_5m_pct"),
                row.get("momentum_15m_pct"),
                row.get("momentum_30m_pct"),
                row.get("vwap"),
                row.get("distance_from_vwap_pct"),
                row.get("trend_label"),
                row.get("trend_score"),
                row.get("reason"),
            ),
        )


def get_latest_session_momentum(symbol: str) -> dict[str, Any] | None:
    init_session_momentum_table()
    with get_connection(DB_PATH) as con:
        row = con.execute(
            """
            SELECT *
            FROM session_momentum
            WHERE symbol = ?
            """,
            (symbol.upper(),),
        ).fetchone()

    return dict(row) if row else None


def refresh_symbol(api: REST, symbol: str) -> dict[str, Any]:
    init_session_momentum_table()
    row = build_session_momentum(api, symbol)
    upsert_session_momentum(row)
    return row


def build_api() -> REST:
    import os

    return REST(
        key_id=os.environ.get("ALPACA_API_KEY", ""),
        secret_key=os.environ.get("ALPACA_SECRET_KEY", ""),
        base_url=get_alpaca_base_url(),
    )


def print_row(row: dict[str, Any]) -> None:
    print(
        f"{row['symbol']:<6} "
        f"label={row['trend_label']:<20} "
        f"score={row['trend_score']:>3} "
        f"session={row['session_return_pct']}% "
        f"5m={row['momentum_5m_pct']}% "
        f"15m={row['momentum_15m_pct']}% "
        f"30m={row['momentum_30m_pct']}% "
        f"vwap_dist={row['distance_from_vwap_pct']}% "
        f"bars={row['bar_count']} "
        f"reason={row['reason']}"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="Refresh one symbol")
    parser.add_argument("--all", action="store_true", help="Refresh all approved symbols")
    args = parser.parse_args()

    if not args.symbol and not args.all:
        parser.error("Provide --symbol SYMBOL or --all")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    api = build_api()

    symbols = APPROVED_SYMBOLS_LIST if args.all else [args.symbol.upper()]

    for symbol in symbols:
        try:
            row = refresh_symbol(api, symbol)
            print_row(row)
        except Exception as e:
            logger.error(f"session momentum refresh failed for {symbol}: {e}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
