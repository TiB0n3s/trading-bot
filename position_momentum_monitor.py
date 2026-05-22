#!/usr/bin/env python3
"""
Position Momentum Monitor

Observe-only first pass:
- Reads current Alpaca positions.
- Reads latest session_momentum for each held symbol.
- Classifies held positions as hold / watch / sell_candidate.
- Does NOT place orders.

Usage:
  python3 position_momentum_monitor.py
"""

from __future__ import annotations

import logging
import os
import math
from datetime import datetime, timedelta
from typing import Any
from pathlib import Path
from db import get_connection
from broker import place_order
from alpaca_trade_api.rest import REST

from runtime_config import get_alpaca_base_url
from market_time import now_et, is_market_hours
from session_momentum import get_latest_session_momentum

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

logger = logging.getLogger("position_momentum_monitor")


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")




MAX_MOMENTUM_AGE_MINUTES = 5
MIN_BARS_FOR_ACTION = 15
AUTO_SELL_COOLDOWN_MINUTES = 30
MIN_HOLD_MINUTES_BEFORE_AUTO_SELL = 15

DB_PATH = Path(__file__).resolve().parent / "trades.db"

POSITION_MOMENTUM_AUTO_SELL = _env_bool("POSITION_MOMENTUM_AUTO_SELL", False)
POSITION_MOMENTUM_SELL_CANDIDATES_ONLY = _env_bool("POSITION_MOMENTUM_SELL_CANDIDATES_ONLY", True)

def build_api() -> REST:
    return REST(
        key_id=os.environ.get("ALPACA_API_KEY", ""),
        secret_key=os.environ.get("ALPACA_SECRET_KEY", ""),
        base_url=get_alpaca_base_url(),
    )

def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


def _is_fresh(row: dict[str, Any] | None, max_age_minutes: int = MAX_MOMENTUM_AGE_MINUTES) -> bool:
    if not row:
        return False

    updated_at = row.get("updated_at")
    if not updated_at:
        return False

    try:
        ts = datetime.strptime(updated_at, "%Y-%m-%d %H:%M:%S")
        age = datetime.now() - ts
        return age.total_seconds() <= max_age_minutes * 60
    except Exception:
        return False


def evaluate_position_momentum(position: Any, session: dict[str, Any] | None) -> dict[str, Any]:
    symbol = getattr(position, "symbol", "UNKNOWN")
    qty = _to_float(getattr(position, "qty", 0))
    unrealized_pl = _to_float(getattr(position, "unrealized_pl", 0))
    unrealized_plpc = _to_float(getattr(position, "unrealized_plpc", 0)) * 100

    if qty <= 0:
        return {
            "symbol": symbol,
            "action": "skip",
            "severity": "not_long",
            "reason": f"qty={qty} is not a long position",
        }

    if not session:
        return {
            "symbol": symbol,
            "action": "hold",
            "severity": "unknown",
            "reason": "no session momentum row",
        }

    if not _is_fresh(session):
        return {
            "symbol": symbol,
            "action": "hold",
            "severity": "stale",
            "reason": f"stale session momentum updated_at={session.get('updated_at')}",
        }

    bar_count = int(session.get("bar_count") or 0)
    if bar_count < MIN_BARS_FOR_ACTION:
        emergency_loss_pct = float(os.getenv("POSITION_MOMENTUM_EMERGENCY_LOSS_PCT", "-1.25"))

        if unrealized_plpc <= emergency_loss_pct:
            return {
                "symbol": symbol,
                "action": "sell_candidate",
                "severity": "emergency_loss",
                "label": session.get("trend_label") or "insufficient_data",
                "score": int(session.get("trend_score") or 0),
                "reason": (
                    f"emergency loss exit: bar_count={bar_count} < {MIN_BARS_FOR_ACTION} "
                    f"unrealized_pl=${unrealized_pl:.2f} "
                    f"unrealized_plpc={unrealized_plpc:.2f}% "
                    f"threshold={emergency_loss_pct:.2f}%"
                ),
            }

        return {
            "symbol": symbol,
            "action": "hold",
            "severity": "insufficient_data",
            "label": session.get("trend_label") or "insufficient_data",
            "score": int(session.get("trend_score") or 0),
            "reason": f"bar_count={bar_count} < {MIN_BARS_FOR_ACTION}",
        }

    label = session.get("trend_label")
    score = int(session.get("trend_score") or 0)
    m5 = _to_float(session.get("momentum_5m_pct"))
    m15 = _to_float(session.get("momentum_15m_pct"))
    m30 = _to_float(session.get("momentum_30m_pct"))
    vwap_dist = _to_float(session.get("distance_from_vwap_pct"))
    session_return = _to_float(session.get("session_return_pct"))

    # Strong sell candidate:
    # The whole session has rolled over, intermediate momentum is negative,
    # and price is below VWAP. This is intentionally conservative.
    
    position_losing = unrealized_pl < 0 or unrealized_plpc < -0.25
    profit_giveback_risk = unrealized_plpc > 0 and m15 < -0.35 and m30 < -0.50
    negative_windows = sum(1 for value in (m5, m15, m30) if value < 0)

    # Failed high-run continuation:
    # Catches positions that were entered into a very strong intraday runner,
    # but the bot's position is now red while the move is rolling over.
    #
    # Example pattern:
    # - Symbol is still up big on the day
    # - Our position is red
    # - Trend score has deteriorated
    # - 15m/30m momentum are both negative
    failed_high_run_session_pct = float(os.getenv("POSITION_MOMENTUM_FAILED_HIGH_RUN_SESSION_PCT", "4.0"))
    failed_high_run_loss_pct = float(os.getenv("POSITION_MOMENTUM_FAILED_HIGH_RUN_LOSS_PCT", "-0.60"))
    failed_high_run_score = float(os.getenv("POSITION_MOMENTUM_FAILED_HIGH_RUN_SCORE", "-4"))
    failed_high_run_15m_pct = float(os.getenv("POSITION_MOMENTUM_FAILED_HIGH_RUN_15M_PCT", "-0.50"))
    failed_high_run_30m_pct = float(os.getenv("POSITION_MOMENTUM_FAILED_HIGH_RUN_30M_PCT", "-0.50"))

    if (
        session_return >= failed_high_run_session_pct
        and unrealized_plpc <= failed_high_run_loss_pct
        and score <= failed_high_run_score
        and m15 <= failed_high_run_15m_pct
        and m30 <= failed_high_run_30m_pct
    ):
        return {
            "symbol": symbol,
            "action": "sell_candidate",
            "severity": "failed_continuation",
            "label": label,
            "score": score,
            "momentum_5m_pct": m5,
            "momentum_15m_pct": m15,
            "momentum_30m_pct": m30,
            "distance_from_vwap_pct": vwap_dist,
            "unrealized_plpc": unrealized_plpc,
            "reason": (
                f"failed high-run continuation: label={label} score={score} "
                f"session={session_return}% 5m={m5}% 15m={m15}% 30m={m30}% "
                f"vwap_dist={vwap_dist}% unrealized_pl=${unrealized_pl:.2f} "
                f"unrealized_plpc={unrealized_plpc:.2f}%"
            ),
        }

    # Trailing high-water profit protection:
    # Protects positions that were meaningfully profitable earlier but are now
    # giving back gains as momentum rolls over.
    high_water_plpc = get_position_high_water_plpc(symbol)

    if high_water_plpc is None:
        high_water_plpc = unrealized_plpc
    else:
        high_water_plpc = max(high_water_plpc, unrealized_plpc)

    giveback_plpc = high_water_plpc - unrealized_plpc

    trailing_profit_min_pct = float(os.getenv("POSITION_MOMENTUM_TRAILING_PROFIT_MIN_PCT", "0.75"))
    trailing_giveback_pct = float(os.getenv("POSITION_MOMENTUM_TRAILING_GIVEBACK_PCT", "0.50"))
    trailing_current_floor_pct = float(os.getenv("POSITION_MOMENTUM_TRAILING_CURRENT_FLOOR_PCT", "-0.25"))

    if (
        high_water_plpc >= trailing_profit_min_pct
        and giveback_plpc >= trailing_giveback_pct
        and negative_windows >= 2
        and unrealized_plpc >= trailing_current_floor_pct
    ):
        return {
            "symbol": symbol,
            "action": "sell_candidate",
            "severity": "profit_protection",
            "label": label,
            "score": score,
            "reason": (
                f"profit protection trailing_giveback: label={label} score={score} "
                f"high_water_plpc={high_water_plpc:.2f}% "
                f"current_plpc={unrealized_plpc:.2f}% "
                f"giveback={giveback_plpc:.2f}% "
                f"negative_windows={negative_windows} session={session_return}% "
                f"5m={m5}% 15m={m15}% 30m={m30}% "
                f"vwap_dist={vwap_dist}% unrealized_pl=${unrealized_pl:.2f}"
            ),
        }


    if (
        (label == "downtrend" or score <= -5)
        and m15 < -0.20
        and m30 < -0.30
        and vwap_dist < -0.15
        and (position_losing or profit_giveback_risk)
    ):
        return {
            "symbol": symbol,
            "action": "sell_candidate",
            "severity": "hard_negative",
            "label": label,
            "score": score,
            "momentum_5m_pct": m5,
            "momentum_15m_pct": m15,
            "momentum_30m_pct": m30,
            "distance_from_vwap_pct": vwap_dist,
            "unrealized_plpc": unrealized_plpc,
            "reason": (
                f"label={label} score={score} session={session_return}% "
                f"5m={m5}% 15m={m15}% 30m={m30}% "
                f"vwap_dist={vwap_dist}% unrealized_pl=${unrealized_pl:.2f} "
                f"unrealized_plpc={unrealized_plpc:.2f}%"
            ),
        }



    # Live profit-protection sell:
    # If a position has meaningful unrealized profit and momentum rolls over,
    # promote it to a sell_candidate so the auto-sell gate can protect gains.
    # Tiered live profit-protection sell:
    # The more profit is available, the less score deterioration we require
    # before allowing the position momentum monitor to protect gains.
    profit_tier_1_pct = float(os.getenv("POSITION_MOMENTUM_PROFIT_TIER_1_PCT", "0.75"))
    profit_tier_1_score = float(os.getenv("POSITION_MOMENTUM_PROFIT_TIER_1_SCORE", "-4"))

    profit_tier_2_pct = float(os.getenv("POSITION_MOMENTUM_PROFIT_TIER_2_PCT", "1.50"))
    profit_tier_2_score = float(os.getenv("POSITION_MOMENTUM_PROFIT_TIER_2_SCORE", "-2"))

    profit_tier_3_pct = float(os.getenv("POSITION_MOMENTUM_PROFIT_TIER_3_PCT", "3.00"))

    profit_protection_tier = None

    if (
        unrealized_plpc >= profit_tier_3_pct
        and negative_windows >= 2
    ):
        profit_protection_tier = "tier_3_large_profit_rollover"

    elif (
        unrealized_plpc >= profit_tier_2_pct
        and score <= profit_tier_2_score
        and negative_windows >= 2
    ):
        profit_protection_tier = "tier_2_profit_rollover"

    elif (
        unrealized_plpc >= profit_tier_1_pct
        and score <= profit_tier_1_score
        and negative_windows >= 2
    ):
        profit_protection_tier = "tier_1_profit_rollover"

    if profit_protection_tier:
        return {
            "symbol": symbol,
            "action": "sell_candidate",
            "severity": "profit_protection",
            "label": label,
            "score": score,
            "reason": (
                f"profit protection {profit_protection_tier}: label={label} score={score} "
                f"negative_windows={negative_windows} session={session_return}% "
                f"5m={m5}% 15m={m15}% 30m={m30}% "
                f"vwap_dist={vwap_dist}% unrealized_pl=${unrealized_pl:.2f} "
                f"unrealized_plpc={unrealized_plpc:.2f}%"
            ),
        }

    # Watch candidate:
    # Fading session with weak intermediate momentum and below VWAP.
    # This is visibility only. It does not auto-sell because action is "watch".
    if (
        (label == "fading" or score <= -3)
        and m15 < 0
        and m30 < 0
        and vwap_dist < -0.10
    ):
        return {
            "symbol": symbol,
            "action": "watch",
            "severity": "soft_negative",
            "label": label,
            "score": score,
            "reason": (
                f"label={label} score={score} session={session_return}% "
                f"5m={m5}% 15m={m15}% 30m={m30}% "
                f"vwap_dist={vwap_dist}% unrealized_pl=${unrealized_pl:.2f} "
                f"unrealized_plpc={unrealized_plpc:.2f}%"
            ),
        }

    return {
        "symbol": symbol,
        "action": "hold",
        "severity": "pass",
        "label": label,
        "score": score,
        "reason": (
            f"label={label} score={score} session={session_return}% "
            f"5m={m5}% 15m={m15}% 30m={m30}% "
            f"vwap_dist={vwap_dist}% unrealized_pl=${unrealized_pl:.2f} "
            f"unrealized_plpc={unrealized_plpc:.2f}%"
        ),
    }

def init_position_momentum_table() -> None:
    with get_connection(DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS position_momentum_checks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                qty REAL,
                action TEXT,
                severity TEXT,
                reason TEXT,
                trend_label TEXT,
                trend_score REAL,
                session_return_pct REAL,
                momentum_5m_pct REAL,
                momentum_15m_pct REAL,
                momentum_30m_pct REAL,
                distance_from_vwap_pct REAL,
                unrealized_pl REAL,
                unrealized_plpc REAL,
                auto_sell_enabled INTEGER DEFAULT 0,
                order_submitted INTEGER DEFAULT 0,
                order_id TEXT
            )
            """
        )


def log_position_momentum_check(position, session, decision, auto_sell_enabled=False, order=None) -> None:
    session = session or {}
    order = order or {}

    with get_connection(DB_PATH) as con:
        con.execute(
            """
            INSERT INTO position_momentum_checks (
                timestamp,
                symbol,
                qty,
                action,
                severity,
                reason,
                trend_label,
                trend_score,
                session_return_pct,
                momentum_5m_pct,
                momentum_15m_pct,
                momentum_30m_pct,
                distance_from_vwap_pct,
                unrealized_pl,
                unrealized_plpc,
                auto_sell_enabled,
                order_submitted,
                order_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                getattr(position, "symbol", None),
                _to_float(getattr(position, "qty", 0)),
                decision.get("action"),
                decision.get("severity"),
                decision.get("reason"),
                session.get("trend_label"),
                session.get("trend_score"),
                session.get("session_return_pct"),
                session.get("momentum_5m_pct"),
                session.get("momentum_15m_pct"),
                session.get("momentum_30m_pct"),
                session.get("distance_from_vwap_pct"),
                _to_float(getattr(position, "unrealized_pl", 0)),
                _to_float(getattr(position, "unrealized_plpc", 0)) * 100,
                1 if auto_sell_enabled else 0,
                1 if order else 0,
                order.get("order_id") if isinstance(order, dict) else None,
            ),
        )

def build_client_order_id(symbol: str) -> str:
    ts = datetime.now().strftime("%Y%m%d%H%M%S")
    return f"posmom-sell-{symbol.lower()}-{ts}"

def latest_approved_buy_time(symbol: str) -> datetime | None:
    """Return latest approved buy timestamp for symbol, if known."""
    with get_connection(DB_PATH) as con:
        row = con.execute(
            """
            SELECT timestamp
            FROM trades
            WHERE symbol = ?
              AND LOWER(action) = 'buy'
              AND approved = 1
            ORDER BY timestamp DESC
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()

    if not row:
        return None

    try:
        return datetime.strptime(row["timestamp"], "%Y-%m-%d %H:%M:%S")
    except Exception:
        return None


def recently_bought(symbol: str, min_hold_minutes: int = MIN_HOLD_MINUTES_BEFORE_AUTO_SELL) -> tuple[bool, str]:
    """Return whether the symbol was bought too recently for auto-sell."""
    ts = latest_approved_buy_time(symbol)

    if not ts:
        return False, "no approved buy timestamp found"

    age = datetime.now() - ts
    age_minutes = age.total_seconds() / 60

    if age_minutes < min_hold_minutes:
        return True, f"latest approved buy {age_minutes:.1f}m ago < min_hold={min_hold_minutes}m"

    return False, f"latest approved buy {age_minutes:.1f}m ago"

def maybe_execute_auto_sell(position, decision, market_open: bool) -> dict[str, Any] | None:
    symbol = getattr(position, "symbol", "UNKNOWN")

    if not POSITION_MOMENTUM_AUTO_SELL:
        return None

    if not market_open:
        logger.warning(f"POSITION MOMENTUM AUTO-SELL skipped for {symbol}: market is closed")
        return None

    if decision.get("action") != "sell_candidate":
        return None

    qty = _to_float(getattr(position, "qty", 0))
    if qty <= 0:
        logger.warning(f"POSITION MOMENTUM AUTO-SELL skipped for {symbol}: qty={qty}")
        return None

    if recently_auto_sold(symbol):
        logger.warning(
            f"POSITION MOMENTUM AUTO-SELL skipped for {symbol}: "
            f"cooldown active ({AUTO_SELL_COOLDOWN_MINUTES}m)"
        )
        return None

    too_recent, hold_reason = recently_bought(symbol)
    if too_recent:
        logger.warning(
            f"POSITION MOMENTUM AUTO-SELL skipped for {symbol}: {hold_reason}"
        )
        return None

        # Profit/risk gate:
    # Do not auto-sell small red positions or tiny green positions.
    # Allow auto-sell only when profit is worth taking or loss is large enough
    # to justify risk control.
    min_profit_to_auto_sell_pct = float(os.getenv("POSITION_MOMENTUM_MIN_PROFIT_SELL_PCT", "0.50"))
    max_loss_to_auto_sell_pct = float(os.getenv("POSITION_MOMENTUM_MAX_LOSS_SELL_PCT", "-1.00"))

    unrealized_plpc = _to_float(getattr(position, "unrealized_plpc", 0)) * 100

    is_trailing_giveback = (
        decision.get("severity") == "profit_protection"
        and "trailing_giveback" in str(decision.get("reason", ""))
    )

    if (
        not is_trailing_giveback
        and max_loss_to_auto_sell_pct < unrealized_plpc < min_profit_to_auto_sell_pct
    ):
        logger.warning(
            f"POSITION MOMENTUM AUTO-SELL blocked for {symbol}: "
            f"unrealized_plpc={unrealized_plpc:.2f}% is between "
            f"risk/profit thresholds {max_loss_to_auto_sell_pct:.2f}% and "
            f"{min_profit_to_auto_sell_pct:.2f}% | {decision.get('reason')}"
        )
        return None

        # Profit-protection / hard-risk gate:
    # Do not auto-sell just because momentum is weak.
    # Auto-sell is allowed only when:
    #   1) profit is worth protecting and momentum has rolled over, or
    #   2) loss is large enough and breakdown is severe.
    profit_protect_min_pct = float(os.getenv("POSITION_MOMENTUM_PROFIT_PROTECT_MIN_PCT", "0.75"))
    profit_protect_score = float(os.getenv("POSITION_MOMENTUM_PROFIT_PROTECT_SCORE", "-2"))
    hard_exit_max_loss_pct = float(os.getenv("POSITION_MOMENTUM_HARD_EXIT_MAX_LOSS_PCT", "-1.00"))
    hard_exit_score = float(os.getenv("POSITION_MOMENTUM_HARD_EXIT_SCORE", "-6"))

    unrealized_plpc = _to_float(getattr(position, "unrealized_plpc", 0)) * 100
    trend_score = _to_float(
        decision.get("trend_score", decision.get("score", 0))
    )

    severity = decision.get("severity")

    profit_protection_exit = (
        severity == "profit_protection"
    )

    emergency_loss_exit = (
        severity == "emergency_loss"
        and unrealized_plpc <= float(os.getenv("POSITION_MOMENTUM_EMERGENCY_LOSS_PCT", "-1.25"))
    )

    severe_breakdown_exit = (
        severity == "hard_negative"
        and unrealized_plpc <= float(os.getenv("POSITION_MOMENTUM_SEVERE_BREAKDOWN_LOSS_PCT", "-0.75"))
        and trend_score <= float(os.getenv("POSITION_MOMENTUM_SEVERE_BREAKDOWN_SCORE", "-5"))
        and _to_float(decision.get("momentum_15m_pct", decision.get("m15", 0))) < float(os.getenv("POSITION_MOMENTUM_SEVERE_BREAKDOWN_15M_PCT", "-0.50"))
        and _to_float(decision.get("momentum_30m_pct", decision.get("m30", 0))) < float(os.getenv("POSITION_MOMENTUM_SEVERE_BREAKDOWN_30M_PCT", "-1.00"))
        and _to_float(decision.get("distance_from_vwap_pct", decision.get("vwap_dist", 0))) < float(os.getenv("POSITION_MOMENTUM_SEVERE_BREAKDOWN_VWAP_PCT", "-0.75"))
    )

    failed_continuation_exit = (
        severity == "failed_continuation"
        and unrealized_plpc <= float(os.getenv("POSITION_MOMENTUM_FAILED_HIGH_RUN_LOSS_PCT", "-0.60"))
    )

    hard_risk_exit = (
        severity == "hard_negative"
        and unrealized_plpc <= hard_exit_max_loss_pct
        and trend_score <= hard_exit_score
    )

    if not (
        profit_protection_exit
        or emergency_loss_exit
        or hard_risk_exit
        or severe_breakdown_exit
        or failed_continuation_exit
    ):
        logger.warning(
            f"POSITION MOMENTUM AUTO-SELL blocked for {symbol}: "
            f"unrealized_plpc={unrealized_plpc:.2f}%, "
            f"trend_score={trend_score:.1f}, "
            f"profit_exit={profit_protection_exit}, "
            f"hard_risk_exit={hard_risk_exit}, "
            f"emergency_loss_exit={emergency_loss_exit}, "
            f"severe_breakdown_exit={severe_breakdown_exit}, "
            f"failed_continuation_exit={failed_continuation_exit} | {decision.get('reason')}"
        )
        return None

    logger.warning(
        f"POSITION MOMENTUM AUTO-SELL allowed for {symbol}: "
        f"unrealized_plpc={unrealized_plpc:.2f}%, "
        f"trend_score={trend_score:.1f}, "
        f"profit_exit={profit_protection_exit}, "
        f"hard_risk_exit={hard_risk_exit}, "
        f"emergency_loss_exit={emergency_loss_exit}, "
        f"severe_breakdown_exit={severe_breakdown_exit}, "
        f"failed_continuation_exit={failed_continuation_exit}"
    )

    client_order_id = build_client_order_id(symbol)

    severity = decision.get("severity")
    position_qty = int(qty)

    if severity == "profit_protection":
        sell_qty = max(1, math.ceil(position_qty * 0.5))
    else:
        sell_qty = position_qty

    logger.warning(
        f"POSITION MOMENTUM AUTO-SELL submitting {symbol}: "
        f"{decision.get('reason')} client_order_id={client_order_id} "
        f"sell_qty={sell_qty}/{position_qty}"
    )

    order = place_order(
        symbol=symbol,
        action="sell",
        position_size_pct=0,
        stop_loss_pct=0,
        take_profit_pct=0,
        risk_level=None,
        client_order_id=client_order_id,
        qty_override=sell_qty,
    )

    if order:
        logger.warning(f"POSITION MOMENTUM AUTO-SELL order submitted for {symbol}: {order}")
        record_auto_sell_action(symbol, decision.get("reason", ""), order)
    else:
        logger.error(f"POSITION MOMENTUM AUTO-SELL failed for {symbol}")

    return order

def init_position_momentum_actions_table() -> None:
    with get_connection(DB_PATH) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS position_momentum_actions (
                symbol TEXT PRIMARY KEY,
                last_action_time TEXT NOT NULL,
                action TEXT NOT NULL,
                reason TEXT,
                order_id TEXT
            )
            """
        )

def get_position_high_water_plpc(symbol: str) -> float | None:
    """
    Return the best unrealized P/L percent seen today for this symbol
    from position_momentum_checks.

    This is observe/stateful only. It lets the monitor detect profit giveback
    from a prior intraday high-water mark.
    """
    today = datetime.now().strftime("%Y-%m-%d")

    try:
        with get_connection(DB_PATH) as con:
            row = con.execute(
                """
                SELECT MAX(unrealized_plpc) AS max_plpc
                FROM position_momentum_checks
                WHERE symbol = ?
                  AND timestamp LIKE ?
                  AND unrealized_plpc IS NOT NULL
                """,
                (symbol, f"{today}%"),
            ).fetchone()

        if row and row["max_plpc"] is not None:
            return float(row["max_plpc"])

    except Exception as e:
        logger.warning(f"Failed to read high-water P/L for {symbol}: {e}")

    return None

def recently_auto_sold(symbol: str, cooldown_minutes: int = AUTO_SELL_COOLDOWN_MINUTES) -> bool:
    with get_connection(DB_PATH) as con:
        row = con.execute(
            """
            SELECT last_action_time
            FROM position_momentum_actions
            WHERE symbol = ?
            """,
            (symbol,),
        ).fetchone()

    if not row:
        return False

    try:
        ts = datetime.strptime(row["last_action_time"], "%Y-%m-%d %H:%M:%S")
        age = datetime.now() - ts
        return age.total_seconds() < cooldown_minutes * 60
    except Exception:
        return True


def record_auto_sell_action(symbol: str, reason: str, order: dict[str, Any] | None) -> None:
    order_id = order.get("order_id") if isinstance(order, dict) else None

    with get_connection(DB_PATH) as con:
        con.execute(
            """
            INSERT INTO position_momentum_actions (
                symbol,
                last_action_time,
                action,
                reason,
                order_id
            ) VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                last_action_time=excluded.last_action_time,
                action=excluded.action,
                reason=excluded.reason,
                order_id=excluded.order_id
            """,
            (
                symbol,
                datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                "auto_sell",
                reason,
                order_id,
            ),
        )

def main() -> int:
    market_now = now_et()
    market_open = is_market_hours(market_now)

    print("=" * 80)
    mode = "AUTO-SELL ENABLED" if POSITION_MOMENTUM_AUTO_SELL else "Observe Only"
    print(f"  Position Momentum Monitor — {mode}")
    print("=" * 80)
    print(f"  market_time_et : {market_now.strftime('%Y-%m-%d %H:%M:%S %Z')}")
    print(f"  market_open    : {market_open}")
    print(f"  auto_sell      : {POSITION_MOMENTUM_AUTO_SELL}")
    print(f"  candidates_only: {POSITION_MOMENTUM_SELL_CANDIDATES_ONLY}")
    print()

    api = build_api()
    positions = api.list_positions()
    init_position_momentum_table()
    init_position_momentum_actions_table()

    if not positions:
        print("No open Alpaca positions.")
        return 0

    rows = []
    for position in sorted(positions, key=lambda p: getattr(p, "symbol", "")):
        symbol = position.symbol
        session = get_latest_session_momentum(symbol)
        decision = evaluate_position_momentum(position, session)
        order = maybe_execute_auto_sell(position, decision, market_open)
        rows.append((position, session, decision))
        log_position_momentum_check(
            position,
            session,
            decision,
            auto_sell_enabled=POSITION_MOMENTUM_AUTO_SELL,
            order=order,
        )

    print(
        f"{'Symbol':<6} {'Action':<15} {'Severity':<16} "
        f"{'Label':<16} {'Score':>5} {'Sess%':>8} {'15m%':>8} {'30m%':>8} {'VWAP%':>8}"
    )
    print(
        f"{'-'*6} {'-'*15} {'-'*16} "
        f"{'-'*16} {'-'*5} {'-'*8} {'-'*8} {'-'*8} {'-'*8}"
    )

    for position, session, decision in rows:
        session = session or {}
        print(
            f"{position.symbol:<6} "
            f"{decision['action']:<15} "
            f"{decision['severity']:<16} "
            f"{str(session.get('trend_label') or '-'):<16} "
            f"{str(session.get('trend_score') if session.get('trend_score') is not None else '-'):>5} "
            f"{str(session.get('session_return_pct') if session.get('session_return_pct') is not None else '-'):>8} "
            f"{str(session.get('momentum_15m_pct') if session.get('momentum_15m_pct') is not None else '-'):>8} "
            f"{str(session.get('momentum_30m_pct') if session.get('momentum_30m_pct') is not None else '-'):>8} "
            f"{str(session.get('distance_from_vwap_pct') if session.get('distance_from_vwap_pct') is not None else '-'):>8}"
        )

        if decision["action"] in ("watch", "sell_candidate"):
            logger.warning(
                "POSITION MOMENTUM %s: %s %s",
                decision["action"].upper(),
                position.symbol,
                decision["reason"],
            )

    print()
    print("Details:")
    for _, _, decision in rows:
        print(f"  {decision['symbol']:<6} {decision['action']:<15} {decision['reason']}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
