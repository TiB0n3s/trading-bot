#!/usr/bin/env python3
"""
Adaptive Position Manager

Reviews open Alpaca positions and recommends exits based on:
- unrealized P&L
- rolling 5m/15m/30m momentum
- VWAP distance
- profit giveback from session peak
- time in trade where available

Safe defaults:
- Observe-only by default
- Does not submit orders unless POSITION_MANAGER_LIVE_SELLS=true
"""

import argparse
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytz

from broker import api
from db import DB_PATH, get_connection
from bot_events import log_event
from session_momentum import get_latest_session_momentum


BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "position_manager_state.json"
ET = pytz.timezone("America/New_York")


LIVE_SELLS = os.getenv("POSITION_MANAGER_LIVE_SELLS", "false").lower() in ("1", "true", "yes", "on")
PARTIAL_SELL_PCT = float(os.getenv("POSITION_MANAGER_PARTIAL_SELL_PCT", "0.50"))
PROMOTE_UNEXECUTABLE_PARTIALS = os.getenv(
    "POSITION_MANAGER_PROMOTE_UNEXECUTABLE_PARTIALS", "true"
).lower() in ("1", "true", "yes", "on")
MIN_PROFIT_PARTIAL_PCT = float(os.getenv("POSITION_MANAGER_MIN_PROFIT_PARTIAL_PCT", "0.75"))
PROFIT_GIVEBACK_TRIGGER_PCT = float(os.getenv("POSITION_MANAGER_PROFIT_GIVEBACK_TRIGGER_PCT", "50"))

# Breakeven/profit-lock protection:
# Prevent winner_became_loser patterns where a trade reaches profit,
# gives it all back, then exits red.
BREAKEVEN_LOCK_TRIGGER_PCT = float(os.getenv("BREAKEVEN_LOCK_TRIGGER_PCT", "0.50"))
BREAKEVEN_LOCK_FLOOR_PCT = float(os.getenv("BREAKEVEN_LOCK_FLOOR_PCT", "0.05"))

# Tighter lock for lower-quality entries such as fade-risk/watch/small-buy setups.
WEAK_SETUP_BREAKEVEN_LOCK_TRIGGER_PCT = float(os.getenv("WEAK_SETUP_BREAKEVEN_LOCK_TRIGGER_PCT", "0.35"))
WEAK_SETUP_BREAKEVEN_LOCK_FLOOR_PCT = float(os.getenv("WEAK_SETUP_BREAKEVEN_LOCK_FLOOR_PCT", "0.02"))
FULL_EXIT_LOSS_PCT = float(os.getenv("POSITION_MANAGER_FULL_EXIT_LOSS_PCT", "-1.25"))
VWAP_LOSS_EXIT_PCT = float(os.getenv("POSITION_MANAGER_VWAP_LOSS_EXIT_PCT", "-0.35"))
CONTINUATION_EXIT_CHECK_ENABLED = os.getenv(
    "POSITION_MANAGER_CONTINUATION_EXIT_CHECK_ENABLED", "true"
).lower() in ("1", "true", "yes", "on")
CONTINUATION_EXIT_HARD_LOSS_FLOOR_PCT = float(
    os.getenv("POSITION_MANAGER_CONTINUATION_HARD_LOSS_FLOOR_PCT", "-0.75")
)
CONTINUATION_EXIT_MIN_MOMENTUM_PCT = float(
    os.getenv("POSITION_MANAGER_CONTINUATION_MIN_MOMENTUM_PCT", "0.05")
)
CONTINUATION_EXIT_MIN_VWAP_DIST_PCT = float(
    os.getenv("POSITION_MANAGER_CONTINUATION_MIN_VWAP_DIST_PCT", "0.05")
)

POSITION_MOMENTUM_SESSION_CONTEXT_ENABLED = os.getenv(
    "POSITION_MOMENTUM_SESSION_CONTEXT_ENABLED", "true"
).lower() in ("1", "true", "yes", "on")
POSITION_MOMENTUM_RETAINED_STRENGTH_ENABLED = os.getenv(
    "POSITION_MOMENTUM_RETAINED_STRENGTH_ENABLED", "true"
).lower() in ("1", "true", "yes", "on")
POSITION_MOMENTUM_STRONG_SCORE_MIN = float(
    os.getenv("POSITION_MOMENTUM_STRONG_SCORE_MIN", "6")
)
POSITION_MOMENTUM_STRONG_RETURN_MIN_PCT = float(
    os.getenv("POSITION_MOMENTUM_STRONG_RETURN_MIN_PCT", "1.0")
)
POSITION_MOMENTUM_STRONG_MINUTES_MIN = float(
    os.getenv("POSITION_MOMENTUM_STRONG_MINUTES_MIN", "20")
)
POSITION_MOMENTUM_RETAINED_MIN_SCORE = float(
    os.getenv("POSITION_MOMENTUM_RETAINED_MIN_SCORE", "3")
)
POSITION_MOMENTUM_RETAINED_MIN_RETURN_PCT = float(
    os.getenv("POSITION_MOMENTUM_RETAINED_MIN_RETURN_PCT", "0.25")
)
POSITION_MOMENTUM_RETAINED_MIN_VWAP_DIST_PCT = float(
    os.getenv("POSITION_MOMENTUM_RETAINED_MIN_VWAP_DIST_PCT", "-0.25")
)
POSITION_MOMENTUM_BREAK_PULLBACK_PCT = float(
    os.getenv("POSITION_MOMENTUM_BREAK_PULLBACK_PCT", "-0.75")
)
POSITION_MOMENTUM_BREAK_VWAP_DIST_PCT = float(
    os.getenv("POSITION_MOMENTUM_BREAK_VWAP_DIST_PCT", "-0.35")
)
POSITION_MOMENTUM_BREAK_15M_PCT = float(
    os.getenv("POSITION_MOMENTUM_BREAK_15M_PCT", "-0.35")
)
POSITION_MOMENTUM_BREAK_30M_PCT = float(
    os.getenv("POSITION_MOMENTUM_BREAK_30M_PCT", "-0.50")
)

# Profit-capture tuning:
# Live in paper only through position_manager. This does not buy, increase size,
# or weaken hard-loss exits. It only adjusts profitable soft exits.
POSITION_MANAGER_PROFIT_CAPTURE_ENABLED = os.getenv(
    "POSITION_MANAGER_PROFIT_CAPTURE_ENABLED", "true"
).lower() in ("1", "true", "yes", "on")

POSITION_MANAGER_TIER2_PEAK_PCT = float(
    os.getenv("POSITION_MANAGER_TIER2_PEAK_PCT", "1.50")
)
POSITION_MANAGER_TIER3_PEAK_PCT = float(
    os.getenv("POSITION_MANAGER_TIER3_PEAK_PCT", "3.00")
)

# If retained session strength is intact, require more giveback before selling
# stronger winners. These are percent-of-peak giveback values, not price pct.
POSITION_MANAGER_RETAINED_TIER2_GIVEBACK_PCT = float(
    os.getenv("POSITION_MANAGER_RETAINED_TIER2_GIVEBACK_PCT", "60")
)
POSITION_MANAGER_RETAINED_TIER3_GIVEBACK_PCT = float(
    os.getenv("POSITION_MANAGER_RETAINED_TIER3_GIVEBACK_PCT", "45")
)

# Avoid selling strong retained-session winners on tiny short-term wiggles.
POSITION_MANAGER_RETAINED_MIN_PROFIT_TO_PROTECT_PCT = float(
    os.getenv("POSITION_MANAGER_RETAINED_MIN_PROFIT_TO_PROTECT_PCT", "0.40")
)

# High-gain lock:
# Protects already-earned open-position profit from excessive giveback.
# Does not affect buys, sizing, hard-loss exits, or red-position exits.
POSITION_MANAGER_HIGH_GAIN_LOCK_ENABLED = os.getenv(
    "POSITION_MANAGER_HIGH_GAIN_LOCK_ENABLED", "true"
).lower() in ("1", "true", "yes", "on")

POSITION_MANAGER_LOCK_TIER1_PEAK_PCT = float(
    os.getenv("POSITION_MANAGER_LOCK_TIER1_PEAK_PCT", "1.00")
)
POSITION_MANAGER_LOCK_TIER1_FLOOR_PCT = float(
    os.getenv("POSITION_MANAGER_LOCK_TIER1_FLOOR_PCT", "0.30")
)

POSITION_MANAGER_LOCK_TIER2_PEAK_PCT = float(
    os.getenv("POSITION_MANAGER_LOCK_TIER2_PEAK_PCT", "1.50")
)
POSITION_MANAGER_LOCK_TIER2_FLOOR_PCT = float(
    os.getenv("POSITION_MANAGER_LOCK_TIER2_FLOOR_PCT", "0.60")
)

POSITION_MANAGER_LOCK_TIER3_PEAK_PCT = float(
    os.getenv("POSITION_MANAGER_LOCK_TIER3_PEAK_PCT", "2.50")
)
POSITION_MANAGER_LOCK_TIER3_FLOOR_PCT = float(
    os.getenv("POSITION_MANAGER_LOCK_TIER3_FLOOR_PCT", "1.00")
)

POSITION_MANAGER_LOCK_TIER4_PEAK_PCT = float(
    os.getenv("POSITION_MANAGER_LOCK_TIER4_PEAK_PCT", "4.00")
)
POSITION_MANAGER_LOCK_TIER4_FLOOR_PCT = float(
    os.getenv("POSITION_MANAGER_LOCK_TIER4_FLOOR_PCT", "1.75")
)

# Bad-entry containment: tighter hard stop for weak entries (error/null setup
# or weak ML bucket) that never showed constructive follow-through. Exits at
# BAD_ENTRY_CONTAINMENT_LOSS_PCT instead of FULL_EXIT_LOSS_PCT when peak
# favorable excursion never exceeded BAD_ENTRY_CONTAINMENT_MAX_PEAK_PCT.
BAD_ENTRY_CONTAINMENT_ENABLED = os.getenv(
    "POSITION_MANAGER_BAD_ENTRY_CONTAINMENT_ENABLED", "true"
).lower() in ("1", "true", "yes", "on")
BAD_ENTRY_CONTAINMENT_LOSS_PCT = float(
    os.getenv("POSITION_MANAGER_BAD_ENTRY_CONTAINMENT_LOSS_PCT", "-0.65")
)
BAD_ENTRY_CONTAINMENT_MAX_PEAK_PCT = float(
    os.getenv("POSITION_MANAGER_BAD_ENTRY_CONTAINMENT_MAX_PEAK_PCT", "0.15")
)


def now_utc():
    return datetime.now(timezone.utc)


def load_state():
    if not STATE_FILE.exists():
        return {}
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def save_state(state):
    STATE_FILE.write_text(json.dumps(state, indent=2, sort_keys=True))


def get_entry_context(symbol):
    """
    Return oldest open entry context from trades.db if available.
    """
    try:
        with get_connection(DB_PATH) as con:
            rows = con.execute("""
                SELECT
                    timestamp, symbol, action, qty, fill_price,
                    market_bias, market_bias_effective,
                    trend_direction, trend_strength,
                    momentum_direction, momentum_pct,
                    session_trend_label, session_trend_score,
                    prediction_score, prediction_decision,
                    setup_label, setup_policy_action,
                    buy_opportunity_score, buy_opportunity_recommendation,
                    ml_prediction_score, ml_prediction_bucket
                FROM trades
                WHERE symbol = ?
                  AND approved = 1
                  AND order_status IN ('filled', 'partially_filled')
                  AND qty IS NOT NULL
                  AND fill_price IS NOT NULL
                  AND action IN ('buy', 'sell')
                ORDER BY timestamp ASC, id ASC
            """, (symbol,)).fetchall()

        lots = []

        for r in rows:
            qty = float(r["qty"] or 0)
            if qty <= 0:
                continue

            if r["action"] == "buy":
                lots.append({"remaining": qty, "row": r})
            elif r["action"] == "sell":
                remaining = qty
                while remaining > 0 and lots:
                    lot = lots[0]
                    matched = min(remaining, lot["remaining"])
                    lot["remaining"] -= matched
                    remaining -= matched
                    if lot["remaining"] <= 0:
                        lots.pop(0)

        if not lots:
            return {}

        r = lots[0]["row"]
        return {
            "entry_timestamp": r["timestamp"],
            "entry_fill_price": r["fill_price"],
            "entry_market_bias": r["market_bias"],
            "entry_market_bias_effective": r["market_bias_effective"],
            "entry_trend": f"{r['trend_direction']}/{r['trend_strength']}",
            "entry_momentum_direction": r["momentum_direction"],
            "entry_momentum_pct": r["momentum_pct"],
            "entry_session_trend_label": r["session_trend_label"],
            "entry_session_trend_score": r["session_trend_score"],
            "entry_prediction_score": r["prediction_score"],
            "entry_prediction_decision": r["prediction_decision"],
            "entry_setup_label": r["setup_label"],
            "entry_setup_policy_action": r["setup_policy_action"],
            "entry_buy_opportunity_score": r["buy_opportunity_score"],
            "entry_buy_opportunity_recommendation": r["buy_opportunity_recommendation"],
            "entry_ml_prediction_score": r["ml_prediction_score"],
            "entry_ml_prediction_bucket": r["ml_prediction_bucket"],
            "open_lot_qty": lots[0]["remaining"],
        }

    except Exception as e:
        return {"entry_context_error": str(e)}


def fetch_intraday_bars(symbol, minutes=60):
    start = (now_utc() - timedelta(minutes=minutes + 5)).isoformat()
    # Keep requests bounded so one slow symbol does not stall the full position review.
    bars = list(api.get_bars(symbol, "1Min", start=start, feed="iex", limit=minutes + 10))

    out = []
    for b in bars:
        try:
            out.append({
                "timestamp": b.t.isoformat(),
                "open": float(b.o),
                "high": float(b.h),
                "low": float(b.l),
                "close": float(b.c),
                "volume": float(getattr(b, "v", 0) or 0),
            })
        except Exception:
            continue

    return out


def calc_vwap(bars):
    total_pv = 0.0
    total_v = 0.0

    for b in bars:
        v = float(b.get("volume") or 0)
        typical = (b["high"] + b["low"] + b["close"]) / 3.0
        total_pv += typical * v
        total_v += v

    if total_v <= 0:
        return None

    return total_pv / total_v


def pct_change(first, last):
    if not first or not last or first <= 0:
        return None
    return (last - first) / first * 100.0


def safe_float(value):
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def high_gain_locked_profit_floor(peak_pl_pct):
    """Return the locked minimum profit floor for a prior peak, or None."""
    if not POSITION_MANAGER_HIGH_GAIN_LOCK_ENABLED:
        return None

    peak = safe_float(peak_pl_pct)
    if peak is None:
        return None

    if peak >= POSITION_MANAGER_LOCK_TIER4_PEAK_PCT:
        return POSITION_MANAGER_LOCK_TIER4_FLOOR_PCT
    if peak >= POSITION_MANAGER_LOCK_TIER3_PEAK_PCT:
        return POSITION_MANAGER_LOCK_TIER3_FLOOR_PCT
    if peak >= POSITION_MANAGER_LOCK_TIER2_PEAK_PCT:
        return POSITION_MANAGER_LOCK_TIER2_FLOOR_PCT
    if peak >= POSITION_MANAGER_LOCK_TIER1_PEAK_PCT:
        return POSITION_MANAGER_LOCK_TIER1_FLOOR_PCT

    return None


def planned_partial_sell_qty(qty, sell_fraction):
    """Return the integer share count a partial exit would submit."""
    try:
        return int(float(qty or 0) * float(sell_fraction or PARTIAL_SELL_PCT))
    except (TypeError, ValueError):
        return 0


def normalize_exit_for_share_qty(action, sell_fraction, qty, severity, reasons):
    """Make soft exits actionable for tiny positions.

    A 1-share position cannot partially exit. When a profit-protection trigger
    fires, promote the decision to a full exit rather than repeatedly logging an
    impossible partial sell.
    """
    if action != "sell_partial" or not PROMOTE_UNEXECUTABLE_PARTIALS:
        return action, sell_fraction, severity

    sell_qty = planned_partial_sell_qty(qty, sell_fraction)
    if sell_qty >= 1:
        return action, sell_fraction, severity

    action = "sell_full"
    sell_fraction = 1.0
    severity = "high" if severity in ("medium", "watch", "pass") else severity
    reasons.append(
        "partial_exit_promoted_to_full: calculated partial sell qty < 1 "
        f"for position qty={qty}; full exit is the smallest actionable protection"
    )
    return action, sell_fraction, severity


def retained_session_strength_state(session_momentum, current_pl_pct):
    """Return retained-strength state for delaying profitable soft exits only.

    Always carries session fields through for logging/reporting, even when the
    current position is not eligible for retained-strength protection.
    """
    session = session_momentum or {}

    session_label = session.get("trend_label")
    session_score = safe_float(session.get("trend_score"))
    session_return = safe_float(session.get("session_return_pct"))
    session_15m = safe_float(session.get("momentum_15m_pct"))
    session_30m = safe_float(session.get("momentum_30m_pct"))
    session_vwap = safe_float(session.get("distance_from_vwap_pct"))

    best_score = safe_float(session.get("best_trend_score"))
    best_return = safe_float(session.get("best_session_return_pct"))
    minutes_strong = safe_float(session.get("minutes_strong"))
    pullback_from_high = safe_float(session.get("pullback_from_session_high_pct"))
    strength_seen = bool(int(session.get("session_strength_seen") or 0))

    base = {
        "session_label": session_label,
        "session_score": session_score,
        "session_return_pct": session_return,
        "session_15m_pct": session_15m,
        "session_30m_pct": session_30m,
        "session_vwap_dist_pct": session_vwap,
        "best_trend_score": best_score,
        "best_session_return_pct": best_return,
        "minutes_strong": minutes_strong,
        "pullback_from_session_high_pct": pullback_from_high,
        "session_strength_seen": strength_seen,
    }

    if not POSITION_MOMENTUM_SESSION_CONTEXT_ENABLED:
        return {
            **base,
            "enabled": False,
            "retained": False,
            "broken": False,
            "reason": "session context disabled",
        }

    if not POSITION_MOMENTUM_RETAINED_STRENGTH_ENABLED:
        return {
            **base,
            "enabled": True,
            "retained": False,
            "broken": False,
            "reason": "retained strength disabled",
        }

    if current_pl_pct <= 0:
        return {
            **base,
            "enabled": True,
            "retained": False,
            "broken": False,
            "reason": "not profitable",
        }

    # A one-refresh spike should not qualify as durable session strength.
    # Strong score can qualify quickly, but return-only strength must persist.
    return_strength_min_observations = min(5.0, POSITION_MOMENTUM_STRONG_MINUTES_MIN)

    strong_seen = (
        strength_seen
        and (
            (
                best_score is not None
                and best_score >= POSITION_MOMENTUM_STRONG_SCORE_MIN
            )
            or (
                best_return is not None
                and best_return >= POSITION_MOMENTUM_STRONG_RETURN_MIN_PCT
                and minutes_strong is not None
                and minutes_strong >= return_strength_min_observations
            )
            or (
                minutes_strong is not None
                and minutes_strong >= POSITION_MOMENTUM_STRONG_MINUTES_MIN
            )
        )
    )

    retained = (
        strong_seen
        and (session_score is None or session_score >= POSITION_MOMENTUM_RETAINED_MIN_SCORE)
        and (session_return is None or session_return >= POSITION_MOMENTUM_RETAINED_MIN_RETURN_PCT)
        and (session_vwap is None or session_vwap >= POSITION_MOMENTUM_RETAINED_MIN_VWAP_DIST_PCT)
    )

    broken = (
        (pullback_from_high is not None and pullback_from_high <= POSITION_MOMENTUM_BREAK_PULLBACK_PCT)
        or (session_vwap is not None and session_vwap <= POSITION_MOMENTUM_BREAK_VWAP_DIST_PCT)
        or (
            session_15m is not None
            and session_30m is not None
            and session_15m <= POSITION_MOMENTUM_BREAK_15M_PCT
            and session_30m <= POSITION_MOMENTUM_BREAK_30M_PCT
        )
    )

    reason = (
        f"label={session_label} score={session_score} return={session_return} "
        f"best_score={best_score} best_return={best_return} "
        f"minutes_strong={minutes_strong} vwap_dist={session_vwap} "
        f"pullback={pullback_from_high}"
    )

    return {
        **base,
        "enabled": True,
        "retained": retained,
        "broken": broken,
        "reason": reason,
    }


def continuation_exit_delay_reason(current_pl_pct, momentum_15m, momentum_30m, vwap_dist_pct):
    """
    Return a hold reason when a soft full-exit trigger conflicts with live tape.

    The hard loss floor is intentionally separate from FULL_EXIT_LOSS_PCT so
    operators can allow some breathing room without weakening the emergency stop.
    """
    if not CONTINUATION_EXIT_CHECK_ENABLED:
        return None

    if current_pl_pct <= CONTINUATION_EXIT_HARD_LOSS_FLOOR_PCT:
        return None

    supports = []

    if momentum_15m is not None and momentum_15m >= CONTINUATION_EXIT_MIN_MOMENTUM_PCT:
        supports.append(f"15m={momentum_15m:.2f}%")
    if momentum_30m is not None and momentum_30m >= CONTINUATION_EXIT_MIN_MOMENTUM_PCT:
        supports.append(f"30m={momentum_30m:.2f}%")
    if vwap_dist_pct is not None and vwap_dist_pct >= CONTINUATION_EXIT_MIN_VWAP_DIST_PCT:
        supports.append(f"vwap_dist={vwap_dist_pct:.2f}%")

    if len(supports) >= 2:
        return (
            "full exit delayed by continuation check "
            f"(current_pl={current_pl_pct:.2f}%, supports={', '.join(supports)})"
        )

    return None


def momentum_window(bars, window):
    if len(bars) < 2:
        return None

    subset = bars[-window:] if len(bars) >= window else bars
    return pct_change(subset[0]["close"], subset[-1]["close"])


def update_peak_state(state, symbol, current_price, avg_entry):
    sym_state = state.setdefault(symbol, {})

    current_pl_pct = pct_change(avg_entry, current_price) or 0.0
    prior_peak = sym_state.get("peak_pl_pct")

    if prior_peak is None or current_pl_pct > prior_peak:
        sym_state["peak_pl_pct"] = round(current_pl_pct, 4)
        sym_state["peak_price"] = round(current_price, 4)
        sym_state["peak_seen_at"] = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S")

    peak_pl_pct = float(sym_state.get("peak_pl_pct") or current_pl_pct)

    giveback_pct = 0.0
    if peak_pl_pct > 0:
        giveback_pct = max(0.0, (peak_pl_pct - current_pl_pct) / peak_pl_pct * 100.0)

    return {
        "current_pl_pct": round(current_pl_pct, 4),
        "peak_pl_pct": round(peak_pl_pct, 4),
        "giveback_pct": round(giveback_pct, 2),
    }



def is_weak_entry_context(entry_ctx):
    """Return True when entry context deserves tighter profit protection."""
    if not entry_ctx:
        return False

    setup_label = str(entry_ctx.get("entry_setup_label") or "").lower()
    setup_action = str(entry_ctx.get("entry_setup_policy_action") or "").lower()
    prediction_decision = str(entry_ctx.get("entry_prediction_decision") or "").lower()
    buy_rec = str(entry_ctx.get("entry_buy_opportunity_recommendation") or "").lower()
    ml_bucket = str(entry_ctx.get("entry_ml_prediction_bucket") or "").lower()

    weak_tokens = (
        "fade_risk",
        "neutral_fade",
        "drift_risk",
        "unclassified",
    )

    if any(token in setup_label for token in weak_tokens):
        return True

    # Setup classification failed at entry time (SIP feed errors, snapshot errors, etc.)
    if setup_action == "error":
        return True

    if prediction_decision in ("watch", "caution"):
        return True

    if buy_rec in ("small_buy_candidate", "watch"):
        return True

    if ml_bucket == "weak_below_45":
        return True

    return False


def is_bad_entry_containment(entry_ctx, peak_pl_pct):
    """
    Return (True, reason) when a weak entry never showed constructive
    follow-through. Used to apply a tighter hard-stop threshold
    (BAD_ENTRY_CONTAINMENT_LOSS_PCT) instead of FULL_EXIT_LOSS_PCT.

    Criteria: entry context is weak (error setup, weak ML bucket, or weak
    label tokens) AND peak favorable excursion never exceeded
    BAD_ENTRY_CONTAINMENT_MAX_PEAK_PCT (i.e., the trade never worked).
    """
    if not BAD_ENTRY_CONTAINMENT_ENABLED:
        return False, None

    if not is_weak_entry_context(entry_ctx):
        return False, None

    if peak_pl_pct > BAD_ENTRY_CONTAINMENT_MAX_PEAK_PCT:
        return False, None

    setup_action = entry_ctx.get("entry_setup_policy_action") or "unknown"
    ml_bucket = entry_ctx.get("entry_ml_prediction_bucket") or "unknown"
    reason = (
        f"bad_entry_containment: weak entry never showed follow-through "
        f"(setup={setup_action}, ml_bucket={ml_bucket}, peak={peak_pl_pct:.2f}%)"
    )
    return True, reason


def evaluate_position(position, state, session_momentum=None):
    symbol = position.symbol
    qty = float(position.qty)
    avg_entry = float(position.avg_entry_price)
    current_price = float(position.current_price)
    unrealized_pl = float(position.unrealized_pl)
    unrealized_plpc = float(position.unrealized_plpc) * 100.0

    entry_ctx = get_entry_context(symbol)

    try:
        bars = fetch_intraday_bars(symbol, minutes=90)
    except Exception as e:
        bars = []
        bar_error = str(e)
    else:
        bar_error = None

    momentum_5m = momentum_window(bars, 5) if bars else None
    momentum_15m = momentum_window(bars, 15) if bars else None
    momentum_30m = momentum_window(bars, 30) if bars else None

    vwap = calc_vwap(bars) if bars else None
    vwap_dist_pct = pct_change(vwap, current_price) if vwap else None

    peak = update_peak_state(state, symbol, current_price, avg_entry)

    reasons = []
    action = "hold"
    sell_fraction = 0.0
    severity = "pass"
    hard_full_exit = False

    current_pl_pct = peak["current_pl_pct"]
    giveback_pct = peak["giveback_pct"]
    peak_pl_pct = peak["peak_pl_pct"]
    retained_strength = retained_session_strength_state(session_momentum, current_pl_pct)
    locked_profit_floor = high_gain_locked_profit_floor(peak_pl_pct)

    # Bad-entry containment: tighter hard stop when a weak entry never showed
    # constructive follow-through. Runs before the normal FULL_EXIT_LOSS_PCT
    # check so it fires sooner on low-quality entries that go immediately wrong.
    _bad_entry, _bad_entry_reason = is_bad_entry_containment(entry_ctx, peak_pl_pct)
    if _bad_entry and current_pl_pct <= BAD_ENTRY_CONTAINMENT_LOSS_PCT:
        action = "sell_full"
        sell_fraction = 1.0
        severity = "high"
        hard_full_exit = True
        reasons.append(
            f"{_bad_entry_reason}, "
            f"loss {current_pl_pct:.2f}% <= containment threshold {BAD_ENTRY_CONTAINMENT_LOSS_PCT:.2f}%"
        )

    # Full exit: losing and momentum/VWAP deteriorating.
    if action == "hold" and current_pl_pct <= FULL_EXIT_LOSS_PCT:
        action = "sell_full"
        sell_fraction = 1.0
        severity = "high"
        hard_full_exit = True
        reasons.append(f"loss {current_pl_pct:.2f}% <= full-exit threshold {FULL_EXIT_LOSS_PCT:.2f}%")

    if action == "hold" and vwap_dist_pct is not None and current_pl_pct < 0 and vwap_dist_pct <= VWAP_LOSS_EXIT_PCT:
        action = "sell_full"
        sell_fraction = 1.0
        severity = "high"
        reasons.append(f"red position below VWAP by {vwap_dist_pct:.2f}%")

    if action == "hold" and momentum_5m is not None and momentum_15m is not None:
        if current_pl_pct < 0 and momentum_5m < -0.20 and momentum_15m < -0.30:
            action = "sell_full"
            sell_fraction = 1.0
            severity = "high"
            reasons.append(f"red position with falling 5m/15m momentum ({momentum_5m:.2f}%, {momentum_15m:.2f}%)")

    # Full exit: breakeven/profit-lock protection.
    # If a position has already moved favorably enough, do not allow it to
    # round-trip back to breakeven/red, especially for weaker entry contexts.
    weak_entry_context = is_weak_entry_context(entry_ctx)
    breakeven_trigger = (
        WEAK_SETUP_BREAKEVEN_LOCK_TRIGGER_PCT
        if weak_entry_context
        else BREAKEVEN_LOCK_TRIGGER_PCT
    )
    breakeven_floor = (
        WEAK_SETUP_BREAKEVEN_LOCK_FLOOR_PCT
        if weak_entry_context
        else BREAKEVEN_LOCK_FLOOR_PCT
    )

    if (
        action == "hold"
        and peak_pl_pct >= breakeven_trigger
        and current_pl_pct <= breakeven_floor
    ):
        action = "sell_full"
        sell_fraction = 1.0
        severity = "high"
        reasons.append(
            f"profit_lock_breakeven_stop: peak {peak_pl_pct:.2f}% >= "
            f"trigger {breakeven_trigger:.2f}%, current {current_pl_pct:.2f}% <= "
            f"floor {breakeven_floor:.2f}%, weak_entry_context={weak_entry_context}"
        )

    if action == "sell_full" and not hard_full_exit:
        delay_reason = continuation_exit_delay_reason(
            current_pl_pct,
            momentum_15m,
            momentum_30m,
            vwap_dist_pct,
        )
        if delay_reason:
            action = "hold"
            sell_fraction = 0.0
            severity = "watch"
            reasons.append(delay_reason)

    # Partial exit: protect profit after favorable move and giveback.
    if action == "hold" and peak_pl_pct >= MIN_PROFIT_PARTIAL_PCT and giveback_pct >= PROFIT_GIVEBACK_TRIGGER_PCT:
        action = "sell_partial"
        sell_fraction = PARTIAL_SELL_PCT
        severity = "medium"
        reasons.append(
            f"profit giveback {giveback_pct:.1f}% from peak {peak_pl_pct:.2f}% "
            f"after reaching min profit {MIN_PROFIT_PARTIAL_PCT:.2f}%"
        )

    if action == "hold" and current_pl_pct >= MIN_PROFIT_PARTIAL_PCT:
        if momentum_5m is not None and momentum_15m is not None and momentum_5m < -0.15 and momentum_15m < 0:
            action = "sell_partial"
            sell_fraction = PARTIAL_SELL_PCT
            severity = "medium"
            reasons.append(f"profitable but momentum fading ({momentum_5m:.2f}%, {momentum_15m:.2f}%)")

    if (
        action == "hold"
        and locked_profit_floor is not None
        and peak_pl_pct > 0
        and current_pl_pct > 0
        and current_pl_pct <= locked_profit_floor
    ):
        if retained_strength.get("retained") and not retained_strength.get("broken"):
            action = "sell_partial"
            sell_fraction = PARTIAL_SELL_PCT
            severity = "medium"
            reasons.append(
                f"high_gain_lock_partial: peak {peak_pl_pct:.2f}% "
                f"fell to {current_pl_pct:.2f}% <= floor {locked_profit_floor:.2f}%; "
                "retained session strength intact"
            )
        else:
            action = "sell_full"
            sell_fraction = 1.0
            severity = "high"
            reasons.append(
                f"high_gain_lock_full: peak {peak_pl_pct:.2f}% "
                f"fell to {current_pl_pct:.2f}% <= floor {locked_profit_floor:.2f}%; "
                "retained session strength absent or broken"
            )

    if (
        POSITION_MANAGER_PROFIT_CAPTURE_ENABLED
        and action in ("sell_partial", "sell_full")
        and not hard_full_exit
        and current_pl_pct > 0
        and retained_strength.get("retained")
        and not retained_strength.get("broken")
    ):
        delay_exit = True
        delay_detail = "retained session strength intact"

        # For larger winners, use peak-aware giveback bands. This keeps the bot
        # from selling too early while a strong session trend remains intact,
        # but still permits exits when the trade has surrendered enough of the move.
        if peak_pl_pct >= POSITION_MANAGER_TIER3_PEAK_PCT:
            delay_exit = giveback_pct < POSITION_MANAGER_RETAINED_TIER3_GIVEBACK_PCT
            delay_detail = (
                f"tier3 peak={peak_pl_pct:.2f}% giveback={giveback_pct:.1f}% "
                f"< {POSITION_MANAGER_RETAINED_TIER3_GIVEBACK_PCT:.1f}%"
            )
        elif peak_pl_pct >= POSITION_MANAGER_TIER2_PEAK_PCT:
            delay_exit = giveback_pct < POSITION_MANAGER_RETAINED_TIER2_GIVEBACK_PCT
            delay_detail = (
                f"tier2 peak={peak_pl_pct:.2f}% giveback={giveback_pct:.1f}% "
                f"< {POSITION_MANAGER_RETAINED_TIER2_GIVEBACK_PCT:.1f}%"
            )
        elif current_pl_pct < POSITION_MANAGER_RETAINED_MIN_PROFIT_TO_PROTECT_PCT:
            delay_exit = True
            delay_detail = (
                f"small retained winner current={current_pl_pct:.2f}% "
                f"< {POSITION_MANAGER_RETAINED_MIN_PROFIT_TO_PROTECT_PCT:.2f}%"
            )

        if delay_exit:
            action = "hold"
            sell_fraction = 0.0
            severity = "watch"
            reasons.append(
                "profit_capture_retained_session: delaying profitable soft exit; "
                + delay_detail
                + "; "
                + str(retained_strength.get("reason"))
            )

    if not reasons:
        reasons.append("no exit trigger")

    action, sell_fraction, severity = normalize_exit_for_share_qty(
        action,
        sell_fraction,
        qty,
        severity,
        reasons,
    )

    return {
        "symbol": symbol,
        "qty": qty,
        "avg_entry": round(avg_entry, 4),
        "current_price": round(current_price, 4),
        "unrealized_pl": round(unrealized_pl, 2),
        "unrealized_pl_pct": round(unrealized_plpc, 3),
        "current_pl_pct_calc": current_pl_pct,
        "peak_pl_pct": peak_pl_pct,
        "profit_giveback_pct": giveback_pct,
        "momentum_5m_pct": round(momentum_5m, 3) if momentum_5m is not None else None,
        "momentum_15m_pct": round(momentum_15m, 3) if momentum_15m is not None else None,
        "momentum_30m_pct": round(momentum_30m, 3) if momentum_30m is not None else None,
        "vwap": round(vwap, 4) if vwap else None,
        "vwap_dist_pct": round(vwap_dist_pct, 3) if vwap_dist_pct is not None else None,
        "session_momentum": session_momentum or {},
        "retained_session_strength": retained_strength,
        "locked_profit_floor_pct": locked_profit_floor,
        "high_gain_lock_enabled": POSITION_MANAGER_HIGH_GAIN_LOCK_ENABLED,
        "session_trend_label": retained_strength.get("session_label"),
        "session_trend_score": retained_strength.get("session_score"),
        "session_return_pct": retained_strength.get("session_return_pct"),
        "session_momentum_15m_pct": retained_strength.get("session_15m_pct"),
        "session_momentum_30m_pct": retained_strength.get("session_30m_pct"),
        "session_distance_from_vwap_pct": retained_strength.get("session_vwap_dist_pct"),
        "session_best_trend_score": retained_strength.get("best_trend_score"),
        "session_best_return_pct": retained_strength.get("best_session_return_pct"),
        "session_minutes_strong": retained_strength.get("minutes_strong"),
        "session_pullback_from_high_pct": retained_strength.get("pullback_from_session_high_pct"),
        "session_strength_seen": retained_strength.get("session_strength_seen"),
        "action": action,
        "sell_fraction": sell_fraction,
        "severity": severity,
        "reasons": reasons,
        "bar_count": len(bars),
        "bar_error": bar_error,
        "entry_context": entry_ctx,
    }


def log_position_manager_exit(decision, order_result, exit_type):
    """Persist position-manager submitted exits to trades.db.

    fill_stream.py/fill_poller.py can later update order_status/fill_price
    by order_id. This row makes the adaptive exit visible to reports and
    learning even if the order starts as pending/submitted.
    """
    try:
        order = order_result.get("order") if isinstance(order_result, dict) else None
        order = order or {}

        order_id = (
            order.get("order_id")
            or order.get("id")
            or getattr(order, "id", None)
        )
        status = (
            order.get("status")
            or getattr(order, "status", None)
            or "submitted"
        )
        qty = (
            order.get("qty")
            or getattr(order, "qty", None)
            or decision.get("sell_qty")
        )

        reason = (
            f"{exit_type}: "
            f"action={decision.get('action')} "
            f"severity={decision.get('severity')} "
            f"reasons={'; '.join(decision.get('reasons') or [])}"
        )

        with get_connection(DB_PATH) as con:
            con.execute("""
                INSERT INTO trades (
                    timestamp,
                    symbol,
                    action,
                    signal_price,
                    approved,
                    rejection_reason,
                    confidence,
                    position_size_pct,
                    stop_loss_pct,
                    take_profit_pct,
                    order_id,
                    order_status,
                    qty,
                    fill_price,

                    market_bias,
                    market_bias_effective,
                    trend_direction,
                    trend_strength,
                    momentum_direction,
                    momentum_pct,
                    session_trend_label,
                    session_trend_score,
                    prediction_score,
                    prediction_decision,
                    setup_label,
                    setup_policy_action,
                    buy_opportunity_score,
                    buy_opportunity_recommendation
                ) VALUES (?, ?, 'sell', ?, 1, ?, ?, 0.0, 0.0, 0.0, ?, ?, ?, NULL,
                          ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S"),
                decision.get("symbol"),
                decision.get("current_price"),
                reason,
                "position_manager",
                order_id,
                status,
                int(float(qty)) if qty is not None else None,

                (decision.get("entry_context") or {}).get("entry_market_bias"),
                (decision.get("entry_context") or {}).get("entry_market_bias_effective"),
                ((decision.get("entry_context") or {}).get("entry_trend") or "/").split("/")[0],
                ((decision.get("entry_context") or {}).get("entry_trend") or "/").split("/")[1],
                "falling" if (
                    (decision.get("momentum_5m_pct") is not None and decision.get("momentum_5m_pct") < 0)
                    or (decision.get("momentum_15m_pct") is not None and decision.get("momentum_15m_pct") < 0)
                ) else "neutral",
                decision.get("momentum_5m_pct"),
                (decision.get("entry_context") or {}).get("entry_session_trend_label"),
                (decision.get("entry_context") or {}).get("entry_session_trend_score"),
                (decision.get("entry_context") or {}).get("entry_prediction_score"),
                (decision.get("entry_context") or {}).get("entry_prediction_decision"),
                (decision.get("entry_context") or {}).get("entry_setup_label"),
                (decision.get("entry_context") or {}).get("entry_setup_policy_action"),
                (decision.get("entry_context") or {}).get("entry_buy_opportunity_score"),
                (decision.get("entry_context") or {}).get("entry_buy_opportunity_recommendation"),
            ))

        return True

    except Exception as e:
        print(f"[WARN] Failed to log position-manager exit to trades.db: {e}")
        return False


def submit_exit(decision):
    """
    Live exit execution.

    Uses existing broker place_order sell path so bracket cancel / position validation
    remains centralized in broker.py. For partial sells, this script submits directly
    through Alpaca because broker.place_order sell currently closes the full position.
    """
    symbol = decision["symbol"]
    action = decision["action"]
    qty = int(float(decision["qty"] or 0))

    if qty <= 0:
        return {"submitted": False, "reason": "qty <= 0"}

    if action == "sell_full":
        # Use existing broker script pathway indirectly by importing here.
        from broker import place_order
        order = place_order(symbol, "sell", 0, 0, 0)
        return {"submitted": bool(order), "order": order}

    if action == "sell_partial":
        sell_qty = planned_partial_sell_qty(qty, decision.get("sell_fraction"))
        if sell_qty < 1:
            if not PROMOTE_UNEXECUTABLE_PARTIALS:
                return {"submitted": False, "reason": "partial sell qty < 1"}
            from broker import place_order
            order = place_order(symbol, "sell", 0, 0, 0)
            return {
                "submitted": bool(order),
                "order": order,
                "promoted_action": "sell_full",
                "reason": "partial sell qty < 1; promoted to full exit",
            }

        open_orders = api.list_orders(status="open", symbols=[symbol])
        for o in open_orders:
            api.cancel_order(o.id)

        order = api.submit_order(
            symbol=symbol,
            qty=sell_qty,
            side="sell",
            type="market",
            time_in_force="day",
        )

        return {
            "submitted": True,
            "order": {
                "order_id": order.id,
                "symbol": symbol,
                "side": "sell",
                "qty": sell_qty,
                "status": getattr(order, "status", None),
            },
        }

    return {"submitted": False, "reason": f"no live action for {action}"}


def render(decisions):
    print("=" * 96)
    print("  Adaptive Position Manager")
    print("=" * 96)
    print(f"  live_sells: {LIVE_SELLS}")
    print()

    if not decisions:
        print("No open Alpaca positions.")
        return

    print(
        f"{'Sym':<6} {'Qty':>6} {'Avg':>9} {'Cur':>9} {'uP&L%':>8} "
        f"{'Peak%':>8} {'Giveback%':>10} {'5m%':>8} {'15m%':>8} {'VWAP%':>8} "
        f"{'Sess':>8} {'Best':>8} {'MinStr':>6} "
        f"{'Action':<12} Reason"
    )
    print("-" * 140)

    for d in decisions:
        print(
            f"{d['symbol']:<6} {d['qty']:>6.0f} {d['avg_entry']:>9.2f} "
            f"{d['current_price']:>9.2f} {d['unrealized_pl_pct']:>8.3f} "
            f"{d['peak_pl_pct']:>8.3f} {d['profit_giveback_pct']:>10.1f} "
            f"{str(d.get('momentum_5m_pct')):>8} "
            f"{str(d.get('momentum_15m_pct')):>8} "
            f"{str(d.get('vwap_dist_pct')):>8} "
            f"{str(d.get('session_trend_score')):>8} "
            f"{str(d.get('session_best_trend_score')):>8} "
            f"{str(d.get('session_minutes_strong')):>6} "
            f"{d['action']:<12} {'; '.join(d['reasons'])}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true", help="Print JSON instead of table")
    parser.add_argument("--live", action="store_true", help="Allow live sells if POSITION_MANAGER_LIVE_SELLS=true")
    args = parser.parse_args()

    state = load_state()

    try:
        positions = api.list_positions()
    except Exception as e:
        raise SystemExit(f"Failed to fetch Alpaca positions: {e}")

    decisions = []
    for p in positions:
        session = None
        try:
            symbol = str(getattr(p, "symbol", "") or "").strip().upper()
            session = get_latest_session_momentum(symbol) if symbol else None
        except Exception as e:
            session = {"trend_label": "unavailable", "reason": f"session momentum read error: {e}"}
        decisions.append(evaluate_position(p, state, session_momentum=session))
    save_state(state)

    for d in decisions:
        log_event(
            event_type="POSITION_MANAGER",
            symbol=d.get("symbol"),
            action="review_position",
            decision=d.get("action"),
            severity=d.get("severity"),
            reason="; ".join(d.get("reasons") or []),
            source="position_manager.py",
            payload=d,
        )

    if args.json:
        print(json.dumps(decisions, indent=2, sort_keys=True))
    else:
        render(decisions)

    if args.live:
        if not LIVE_SELLS:
            print()
            print("Live mode requested, but POSITION_MANAGER_LIVE_SELLS is not true. No orders submitted.")
            return

        print()
        print("── Live actions ──────────────────────────────────────")
        for d in decisions:
            if d["action"] in ("sell_partial", "sell_full"):
                result = submit_exit(d)
                print(f"{d['symbol']} {d['action']}: {result}")

                log_event(
                    event_type="POSITION_MANAGER_ORDER",
                    symbol=d.get("symbol"),
                    action=d.get("action"),
                    decision="submitted" if isinstance(result, dict) and result.get("submitted") else "not_submitted",
                    severity=d.get("severity"),
                    reason="; ".join(d.get("reasons") or []),
                    source="position_manager.py",
                    payload={"decision": d, "result": result},
                )

                if isinstance(result, dict) and result.get("submitted"):
                    exit_type = (
                        "position_manager_partial_exit"
                        if d.get("action") == "sell_partial"
                        else "position_manager_full_exit"
                    )
                    logged = log_position_manager_exit(d, result, exit_type)
                    print(f"{d['symbol']} db_logged={logged}")


if __name__ == "__main__":
    main()
