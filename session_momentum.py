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
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

BASE_DIR = Path(__file__).resolve().parent
VENV_PYTHON = BASE_DIR / "venv" / "bin" / "python"
ENV_FILE = Path("/etc/trading-bot.env")


def reexec_under_venv_if_available() -> None:
    if not VENV_PYTHON.exists():
        return

    venv_dir = VENV_PYTHON.parent.parent.resolve()
    current_prefix = Path(sys.prefix).resolve()
    if current_prefix == venv_dir:
        return

    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve())] + sys.argv[1:])


reexec_under_venv_if_available()


def load_env_file(path: Path = ENV_FILE) -> bool:
    if not path.exists():
        return False

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

    return True


load_env_file()

from db import get_connection
from services.market_data_service import market_data_service
from symbols_config import APPROVED_SYMBOLS_LIST

logger = logging.getLogger("session_momentum")

DB_PATH = BASE_DIR / "trades.db"

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
                reason TEXT,
                best_trend_score INTEGER,
                best_session_return_pct REAL,
                best_distance_from_vwap_pct REAL,
                minutes_strong INTEGER,
                strength_first_seen_at TEXT,
                strength_last_seen_at TEXT,
                pullback_from_session_high_pct REAL,
                session_strength_seen INTEGER
            )
            """
        )

        for col, typ in (
            ("best_trend_score", "INTEGER"),
            ("best_session_return_pct", "REAL"),
            ("best_distance_from_vwap_pct", "REAL"),
            ("minutes_strong", "INTEGER"),
            ("strength_first_seen_at", "TEXT"),
            ("strength_last_seen_at", "TEXT"),
            ("pullback_from_session_high_pct", "REAL"),
            ("session_strength_seen", "INTEGER"),
        ):
            existing = {
                r["name"] for r in con.execute("PRAGMA table_info(session_momentum)").fetchall()
            }
            if col not in existing:
                con.execute(f"ALTER TABLE session_momentum ADD COLUMN {col} {typ}")


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


def _bar_high(bar: Any) -> float | None:
    return _safe_float(getattr(bar, "h", None))


def _bar_low(bar: Any) -> float | None:
    return _safe_float(getattr(bar, "l", None))


def _bar_typical_price(bar: Any) -> float | None:
    """Typical price (H+L+C)/3 — standard VWAP numerator."""
    h = _bar_high(bar)
    lo = _bar_low(bar)
    c = _bar_close(bar)
    if h is None or lo is None or c is None:
        return None
    return (h + lo + c) / 3.0


def _bar_volume(bar: Any) -> float:
    return _safe_float(getattr(bar, "v", None)) or 0.0


def _compute_vwap(bars: list[Any]) -> float | None:
    total_pv = 0.0
    total_v = 0.0

    for bar in bars:
        tp = _bar_typical_price(bar)
        volume = _bar_volume(bar)
        if tp is None or volume <= 0:
            continue
        total_pv += tp * volume
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


def build_session_momentum(api: Any, symbol: str) -> dict[str, Any]:
    symbol = symbol.upper()
    start = (datetime.now(timezone.utc) - timedelta(minutes=LOOKBACK_MINUTES)).isoformat()

    bars = market_data_service.get_bars_with_fallback(symbol, "1Min", start=start, feed="iex")
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


def _is_strong_session(row: dict[str, Any]) -> bool:
    score = _safe_float(row.get("trend_score")) or 0.0
    session_return = _safe_float(row.get("session_return_pct")) or 0.0
    return score >= 6 or session_return >= 1.0


def _merge_retained_strength(row: dict[str, Any], previous: dict[str, Any] | None) -> dict[str, Any]:
    """Carry session-strength high-water marks across refreshes for the same trading day."""
    previous = previous or {}
    merged = dict(row)

    now = row.get("updated_at")
    score = _safe_float(row.get("trend_score"))
    session_return = _safe_float(row.get("session_return_pct"))
    vwap_dist = _safe_float(row.get("distance_from_vwap_pct"))

    prev_best_score = _safe_float(previous.get("best_trend_score"))
    prev_best_return = _safe_float(previous.get("best_session_return_pct"))
    prev_best_vwap = _safe_float(previous.get("best_distance_from_vwap_pct"))
    prev_minutes_strong = int(previous.get("minutes_strong") or 0)
    prev_seen = int(previous.get("session_strength_seen") or 0)

    best_score = max(
        [v for v in (prev_best_score, score) if v is not None],
        default=None,
    )
    best_return = max(
        [v for v in (prev_best_return, session_return) if v is not None],
        default=None,
    )
    best_vwap = max(
        [v for v in (prev_best_vwap, vwap_dist) if v is not None],
        default=None,
    )

    strong_now = _is_strong_session(row)
    session_strength_seen = 1 if (prev_seen or strong_now) else 0

    first_seen = previous.get("strength_first_seen_at")
    last_seen = previous.get("strength_last_seen_at")

    if strong_now:
        if not first_seen:
            first_seen = now
        last_seen = now
        # session_momentum refresh usually runs every 1-2 minutes; count conservatively.
        prev_minutes_strong += 1

    pullback_from_high = None
    if session_return is not None and best_return is not None:
        pullback_from_high = session_return - best_return

    merged.update({
        "best_trend_score": int(best_score) if best_score is not None else None,
        "best_session_return_pct": round(best_return, 3) if best_return is not None else None,
        "best_distance_from_vwap_pct": round(best_vwap, 3) if best_vwap is not None else None,
        "minutes_strong": prev_minutes_strong,
        "strength_first_seen_at": first_seen,
        "strength_last_seen_at": last_seen,
        "pullback_from_session_high_pct": round(pullback_from_high, 3) if pullback_from_high is not None else None,
        "session_strength_seen": session_strength_seen,
    })
    return merged


def upsert_session_momentum(row: dict[str, Any]) -> None:
    init_session_momentum_table()

    with get_connection(DB_PATH) as con:
        previous_row = con.execute(
            "SELECT * FROM session_momentum WHERE symbol = ?",
            (str(row.get("symbol") or "").upper(),),
        ).fetchone()
        previous = dict(previous_row) if previous_row else None

        row = _merge_retained_strength(row, previous)

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
                reason,
                best_trend_score,
                best_session_return_pct,
                best_distance_from_vwap_pct,
                minutes_strong,
                strength_first_seen_at,
                strength_last_seen_at,
                pullback_from_session_high_pct,
                session_strength_seen
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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
                reason=excluded.reason,
                best_trend_score=excluded.best_trend_score,
                best_session_return_pct=excluded.best_session_return_pct,
                best_distance_from_vwap_pct=excluded.best_distance_from_vwap_pct,
                minutes_strong=excluded.minutes_strong,
                strength_first_seen_at=excluded.strength_first_seen_at,
                strength_last_seen_at=excluded.strength_last_seen_at,
                pullback_from_session_high_pct=excluded.pullback_from_session_high_pct,
                session_strength_seen=excluded.session_strength_seen
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
                row.get("best_trend_score"),
                row.get("best_session_return_pct"),
                row.get("best_distance_from_vwap_pct"),
                row.get("minutes_strong"),
                row.get("strength_first_seen_at"),
                row.get("strength_last_seen_at"),
                row.get("pullback_from_session_high_pct"),
                row.get("session_strength_seen"),
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


def refresh_symbol(api: Any, symbol: str) -> dict[str, Any]:
    init_session_momentum_table()
    row = build_session_momentum(api, symbol)
    upsert_session_momentum(row)
    return get_latest_session_momentum(symbol) or row


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
        f"best_score={row.get('best_trend_score')} "
        f"best_return={row.get('best_session_return_pct')}% "
        f"minutes_strong={row.get('minutes_strong')} "
        f"pullback={row.get('pullback_from_session_high_pct')}% "
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

    api = None

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
