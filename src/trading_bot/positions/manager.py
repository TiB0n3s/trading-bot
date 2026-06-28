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
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytz

BASE_DIR = Path(__file__).resolve().parents[3]
SCRIPTS_DIR = BASE_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from bot_events import log_event
from services.broker_service import broker_service
from services.position_market_data_service import position_market_data_service
from session_momentum import get_latest_session_momentum

from config.position_manager import load_position_manager_config
from repositories import position_repo

STATE_FILE = BASE_DIR / "position_manager_state.json"
ET = pytz.timezone("America/New_York")

_POSITION_MANAGER_CFG = load_position_manager_config()


LIVE_SELLS = _POSITION_MANAGER_CFG.live_sells
PARTIAL_SELL_PCT = _POSITION_MANAGER_CFG.partial_sell_pct
PROMOTE_UNEXECUTABLE_PARTIALS = _POSITION_MANAGER_CFG.promote_unexecutable_partials
MIN_PROFIT_PARTIAL_PCT = _POSITION_MANAGER_CFG.min_profit_partial_pct
# Partial exits cancel the protective bracket legs, then must wait for Alpaca to
# release the held shares before the market sell. Poll within the SAME pass so we
# don't leave the position with canceled brackets AND no exit until the next cron
# cycle (unprotected window; the partial may never fire if the trigger flips).
_PARTIAL_CANCEL_POLL_ATTEMPTS = 10
_PARTIAL_CANCEL_POLL_DELAY_SEC = 0.5
PROFIT_GIVEBACK_TRIGGER_PCT = _POSITION_MANAGER_CFG.profit_giveback_trigger_pct

# Breakeven/profit-lock protection:
# Prevent winner_became_loser patterns where a trade reaches profit,
# gives it all back, then exits red.
BREAKEVEN_LOCK_TRIGGER_PCT = _POSITION_MANAGER_CFG.breakeven_lock_trigger_pct
BREAKEVEN_LOCK_FLOOR_PCT = _POSITION_MANAGER_CFG.breakeven_lock_floor_pct

# Tighter lock for lower-quality entries such as fade-risk/watch/small-buy setups.
WEAK_SETUP_BREAKEVEN_LOCK_TRIGGER_PCT = _POSITION_MANAGER_CFG.weak_setup_breakeven_lock_trigger_pct
WEAK_SETUP_BREAKEVEN_LOCK_FLOOR_PCT = _POSITION_MANAGER_CFG.weak_setup_breakeven_lock_floor_pct
FULL_EXIT_LOSS_PCT = _POSITION_MANAGER_CFG.full_exit_loss_pct
VWAP_LOSS_EXIT_PCT = _POSITION_MANAGER_CFG.vwap_loss_exit_pct
CONTINUATION_EXIT_CHECK_ENABLED = _POSITION_MANAGER_CFG.continuation_exit_check_enabled
CONTINUATION_EXIT_HARD_LOSS_FLOOR_PCT = _POSITION_MANAGER_CFG.continuation_hard_loss_floor_pct
CONTINUATION_EXIT_MIN_MOMENTUM_PCT = _POSITION_MANAGER_CFG.continuation_min_momentum_pct
CONTINUATION_EXIT_MIN_VWAP_DIST_PCT = _POSITION_MANAGER_CFG.continuation_min_vwap_dist_pct

POSITION_MOMENTUM_SESSION_CONTEXT_ENABLED = (
    _POSITION_MANAGER_CFG.position_momentum_session_context_enabled
)
POSITION_MOMENTUM_RETAINED_STRENGTH_ENABLED = (
    _POSITION_MANAGER_CFG.position_momentum_retained_strength_enabled
)
POSITION_MOMENTUM_STRONG_SCORE_MIN = _POSITION_MANAGER_CFG.momentum_strong_score_min
POSITION_MOMENTUM_STRONG_RETURN_MIN_PCT = _POSITION_MANAGER_CFG.momentum_strong_return_min_pct
POSITION_MOMENTUM_STRONG_MINUTES_MIN = _POSITION_MANAGER_CFG.momentum_strong_minutes_min
POSITION_MOMENTUM_RETAINED_MIN_SCORE = _POSITION_MANAGER_CFG.momentum_retained_min_score
POSITION_MOMENTUM_RETAINED_MIN_RETURN_PCT = _POSITION_MANAGER_CFG.momentum_retained_min_return_pct
POSITION_MOMENTUM_RETAINED_MIN_VWAP_DIST_PCT = (
    _POSITION_MANAGER_CFG.momentum_retained_min_vwap_dist_pct
)
POSITION_MOMENTUM_BREAK_PULLBACK_PCT = _POSITION_MANAGER_CFG.momentum_break_pullback_pct
POSITION_MOMENTUM_BREAK_VWAP_DIST_PCT = _POSITION_MANAGER_CFG.momentum_break_vwap_dist_pct
POSITION_MOMENTUM_BREAK_15M_PCT = _POSITION_MANAGER_CFG.momentum_break_15m_pct
POSITION_MOMENTUM_BREAK_30M_PCT = _POSITION_MANAGER_CFG.momentum_break_30m_pct

# Profit-capture tuning:
# Live in paper only through position_manager. This does not buy, increase size,
# or weaken hard-loss exits. It only adjusts profitable soft exits.
POSITION_MANAGER_PROFIT_CAPTURE_ENABLED = _POSITION_MANAGER_CFG.profit_capture_enabled

POSITION_MANAGER_TIER2_PEAK_PCT = _POSITION_MANAGER_CFG.tier2_peak_pct
POSITION_MANAGER_TIER3_PEAK_PCT = _POSITION_MANAGER_CFG.tier3_peak_pct

# If retained session strength is intact, require more giveback before selling
# stronger winners. These are percent-of-peak giveback values, not price pct.
POSITION_MANAGER_RETAINED_TIER2_GIVEBACK_PCT = _POSITION_MANAGER_CFG.retained_tier2_giveback_pct
POSITION_MANAGER_RETAINED_TIER3_GIVEBACK_PCT = _POSITION_MANAGER_CFG.retained_tier3_giveback_pct

# Avoid selling strong retained-session winners on tiny short-term wiggles.
POSITION_MANAGER_RETAINED_MIN_PROFIT_TO_PROTECT_PCT = (
    _POSITION_MANAGER_CFG.retained_min_profit_to_protect_pct
)

# High-gain lock:
# Protects already-earned open-position profit from excessive giveback.
# Does not affect buys, sizing, hard-loss exits, or red-position exits.
POSITION_MANAGER_HIGH_GAIN_LOCK_ENABLED = _POSITION_MANAGER_CFG.high_gain_lock_enabled

POSITION_MANAGER_LOCK_TIER1_PEAK_PCT = _POSITION_MANAGER_CFG.lock_tier1_peak_pct
POSITION_MANAGER_LOCK_TIER1_FLOOR_PCT = _POSITION_MANAGER_CFG.lock_tier1_floor_pct

POSITION_MANAGER_LOCK_TIER2_PEAK_PCT = _POSITION_MANAGER_CFG.lock_tier2_peak_pct
POSITION_MANAGER_LOCK_TIER2_FLOOR_PCT = _POSITION_MANAGER_CFG.lock_tier2_floor_pct

POSITION_MANAGER_LOCK_TIER3_PEAK_PCT = _POSITION_MANAGER_CFG.lock_tier3_peak_pct
POSITION_MANAGER_LOCK_TIER3_FLOOR_PCT = _POSITION_MANAGER_CFG.lock_tier3_floor_pct

POSITION_MANAGER_LOCK_TIER4_PEAK_PCT = _POSITION_MANAGER_CFG.lock_tier4_peak_pct
POSITION_MANAGER_LOCK_TIER4_FLOOR_PCT = _POSITION_MANAGER_CFG.lock_tier4_floor_pct

# Bad-entry containment: tighter hard stop for weak entries (error/null setup
# or weak ML bucket) that never showed constructive follow-through. Exits at
# BAD_ENTRY_CONTAINMENT_LOSS_PCT instead of FULL_EXIT_LOSS_PCT when peak
# favorable excursion never exceeded BAD_ENTRY_CONTAINMENT_MAX_PEAK_PCT.
BAD_ENTRY_CONTAINMENT_ENABLED = _POSITION_MANAGER_CFG.bad_entry_containment_enabled
BAD_ENTRY_CONTAINMENT_LOSS_PCT = _POSITION_MANAGER_CFG.bad_entry_containment_loss_pct
BAD_ENTRY_CONTAINMENT_MAX_PEAK_PCT = _POSITION_MANAGER_CFG.bad_entry_containment_max_peak_pct

# Peak-aware breakeven lock.
# The floor that the current P&L must not fall below rises with the peak,
# so trades that have demonstrated real profit cannot fully round-trip.
# Strong entries (3 tiers): more room at each level.
PEAK_LOCK_TIER1_PEAK_PCT = _POSITION_MANAGER_CFG.peak_lock_tier1_peak_pct
PEAK_LOCK_TIER1_FLOOR_PCT = _POSITION_MANAGER_CFG.peak_lock_tier1_floor_pct
PEAK_LOCK_TIER2_PEAK_PCT = _POSITION_MANAGER_CFG.peak_lock_tier2_peak_pct
PEAK_LOCK_TIER2_FLOOR_PCT = _POSITION_MANAGER_CFG.peak_lock_tier2_floor_pct
PEAK_LOCK_TIER3_PEAK_PCT = _POSITION_MANAGER_CFG.peak_lock_tier3_peak_pct
PEAK_LOCK_TIER3_FLOOR_PCT = _POSITION_MANAGER_CFG.peak_lock_tier3_floor_pct
# Weak entries (2 tiers): faster ratchet once meaningfully green.
WEAK_PEAK_LOCK_TIER1_PEAK_PCT = _POSITION_MANAGER_CFG.weak_peak_lock_tier1_peak_pct
WEAK_PEAK_LOCK_TIER1_FLOOR_PCT = _POSITION_MANAGER_CFG.weak_peak_lock_tier1_floor_pct
WEAK_PEAK_LOCK_TIER2_PEAK_PCT = _POSITION_MANAGER_CFG.weak_peak_lock_tier2_peak_pct
WEAK_PEAK_LOCK_TIER2_FLOOR_PCT = _POSITION_MANAGER_CFG.weak_peak_lock_tier2_floor_pct

# Quality-split exit thresholds — three tiers:
# Strong conviction: looser giveback tolerance, higher min-profit bar before partial exit.
# Normal strong: standard room (60% giveback, 0.75% min).
# Weak: managed tightly once green (35% giveback, 0.35% min).
STRONG_CONVICTION_PROFIT_GIVEBACK_TRIGGER_PCT = (
    _POSITION_MANAGER_CFG.strong_conviction_profit_giveback_trigger_pct
)
STRONG_CONVICTION_MIN_PROFIT_PARTIAL_PCT = (
    _POSITION_MANAGER_CFG.strong_conviction_min_profit_partial_pct
)
STRONG_ENTRY_PROFIT_GIVEBACK_TRIGGER_PCT = (
    _POSITION_MANAGER_CFG.strong_entry_profit_giveback_trigger_pct
)
WEAK_ENTRY_PROFIT_GIVEBACK_TRIGGER_PCT = (
    _POSITION_MANAGER_CFG.weak_entry_profit_giveback_trigger_pct
)
WEAK_ENTRY_MIN_PROFIT_PARTIAL_PCT = _POSITION_MANAGER_CFG.weak_entry_min_profit_partial_pct

PROACTIVE_PROFIT_CAPTURE_ENABLED = _POSITION_MANAGER_CFG.proactive_profit_capture_enabled
PROACTIVE_STRONG_MIN_PEAK_PCT = _POSITION_MANAGER_CFG.proactive_strong_min_peak_pct
PROACTIVE_STRONG_MIN_CURRENT_PCT = _POSITION_MANAGER_CFG.proactive_strong_min_current_pct
PROACTIVE_STRONG_GIVEBACK_PCT = _POSITION_MANAGER_CFG.proactive_strong_giveback_pct
PROACTIVE_WEAK_MIN_PEAK_PCT = _POSITION_MANAGER_CFG.proactive_weak_min_peak_pct
PROACTIVE_WEAK_MIN_CURRENT_PCT = _POSITION_MANAGER_CFG.proactive_weak_min_current_pct
PROACTIVE_WEAK_GIVEBACK_PCT = _POSITION_MANAGER_CFG.proactive_weak_giveback_pct

# Exit-pattern pressure:
# A bounded profit-protection layer for positions that are already green.
# It does not buy, increase size, weaken hard stops, or turn a red position into
# a hold. It can only trigger a partial profit capture when live momentum/VWAP
# pattern evidence suggests a winner is starting to fail.
EXIT_PATTERN_PROFIT_CAPTURE_ENABLED = _POSITION_MANAGER_CFG.exit_pattern_profit_capture_enabled
EXIT_PATTERN_STRONG_MIN_PEAK_PCT = _POSITION_MANAGER_CFG.exit_pattern_strong_min_peak_pct
EXIT_PATTERN_STRONG_MIN_CURRENT_PCT = _POSITION_MANAGER_CFG.exit_pattern_strong_min_current_pct
EXIT_PATTERN_WEAK_MIN_PEAK_PCT = _POSITION_MANAGER_CFG.exit_pattern_weak_min_peak_pct
EXIT_PATTERN_WEAK_MIN_CURRENT_PCT = _POSITION_MANAGER_CFG.exit_pattern_weak_min_current_pct
EXIT_PATTERN_MIN_ADVERSE_SIGNALS = _POSITION_MANAGER_CFG.exit_pattern_min_adverse_signals
EXIT_PATTERN_WEAK_GIVEBACK_PCT = _POSITION_MANAGER_CFG.exit_pattern_weak_giveback_pct

# Auto-buy coordination:
# The buy engine and exit engine run independently. A fresh auto-buy position
# should not be immediately closed by soft profit locks before the entry thesis
# has had time to play out. Severe loss/risk exits remain active.
AUTO_BUY_MIN_HOLD_MINUTES = _POSITION_MANAGER_CFG.auto_buy_min_hold_minutes
AUTO_BUY_MIN_HOLD_HARD_LOSS_PCT = _POSITION_MANAGER_CFG.auto_buy_min_hold_hard_loss_pct
AUTO_BUY_STRONG_ENTRY_ML_MIN = _POSITION_MANAGER_CFG.auto_buy_strong_entry_ml_min
AUTO_BUY_STRONG_ENTRY_OPPORTUNITY_MIN = _POSITION_MANAGER_CFG.auto_buy_strong_entry_opportunity_min


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
        rows = position_repo.entry_context_rows(symbol)
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
            "entry_confidence": r["confidence"],
            "entry_rejection_reason": r["rejection_reason"],
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
    return position_market_data_service.fetch_intraday_bars(symbol, minutes=minutes)


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


def parse_entry_timestamp(value):
    if not value:
        return None

    if isinstance(value, datetime):
        dt = value
    else:
        text = str(value).strip()
        if not text:
            return None
        try:
            dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        except Exception:
            dt = None
            for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S"):
                try:
                    dt = datetime.strptime(text[:19], fmt)
                    break
                except Exception:
                    continue
            if dt is None:
                return None

    if dt.tzinfo is None:
        return ET.localize(dt)
    return dt.astimezone(ET)


def entry_age_minutes(entry_ctx, now=None):
    entry_ts = parse_entry_timestamp((entry_ctx or {}).get("entry_timestamp"))
    if entry_ts is None:
        return None

    now = now or datetime.now(ET)
    if now.tzinfo is None:
        now = ET.localize(now)
    else:
        now = now.astimezone(ET)

    return max(0.0, (now - entry_ts).total_seconds() / 60.0)


def is_auto_buy_entry(entry_ctx):
    if not entry_ctx:
        return False

    confidence = str(entry_ctx.get("entry_confidence") or "").lower()
    reason = str(entry_ctx.get("entry_rejection_reason") or "").lower()
    decision = str(entry_ctx.get("entry_prediction_decision") or "").lower()

    return (
        "auto_buy" in confidence
        or "auto_buy" in reason
        or "auto-buy" in reason
        or decision == "auto_buy_manager"
    )


def is_high_confidence_auto_buy_entry(entry_ctx):
    if not is_auto_buy_entry(entry_ctx):
        return False

    ml_score = safe_float(entry_ctx.get("entry_ml_prediction_score"))
    opp_score = safe_float(entry_ctx.get("entry_buy_opportunity_score"))
    ml_bucket = str(entry_ctx.get("entry_ml_prediction_bucket") or "").lower()
    buy_rec = str(entry_ctx.get("entry_buy_opportunity_recommendation") or "").lower()
    setup_action = str(entry_ctx.get("entry_setup_policy_action") or "").lower()

    if ml_score is not None and ml_score >= AUTO_BUY_STRONG_ENTRY_ML_MIN:
        return True
    if opp_score is not None and opp_score >= AUTO_BUY_STRONG_ENTRY_OPPORTUNITY_MIN:
        return True
    if ml_bucket in ("high_55_plus", "mid_50_55"):
        return True
    if buy_rec == "strong_buy_candidate":
        return True
    return setup_action in ("allow", "boost")


def auto_buy_min_hold_state(entry_ctx, current_pl_pct, now=None):
    age = entry_age_minutes(entry_ctx, now=now)
    auto_buy = is_auto_buy_entry(entry_ctx)
    high_confidence = is_high_confidence_auto_buy_entry(entry_ctx)
    severe_loss = current_pl_pct <= AUTO_BUY_MIN_HOLD_HARD_LOSS_PCT
    active = (
        AUTO_BUY_MIN_HOLD_MINUTES > 0
        and auto_buy
        and age is not None
        and age < AUTO_BUY_MIN_HOLD_MINUTES
        and not severe_loss
    )

    age_text = "unknown" if age is None else f"{age:.1f}m"
    return {
        "enabled": AUTO_BUY_MIN_HOLD_MINUTES > 0,
        "active": active,
        "auto_buy_entry": auto_buy,
        "high_confidence_entry": high_confidence,
        "entry_age_minutes": round(age, 2) if age is not None else None,
        "min_hold_minutes": AUTO_BUY_MIN_HOLD_MINUTES,
        "hard_loss_pct": AUTO_BUY_MIN_HOLD_HARD_LOSS_PCT,
        "severe_loss": severe_loss,
        "reason": (
            f"auto_buy_min_hold: age={age_text} "
            f"< {AUTO_BUY_MIN_HOLD_MINUTES:.1f}m; "
            f"current_pl={current_pl_pct:.2f}% "
            f"> hard_loss={AUTO_BUY_MIN_HOLD_HARD_LOSS_PCT:.2f}%; "
            f"high_confidence={high_confidence}"
        ),
    }


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

    strong_seen = strength_seen and (
        (best_score is not None and best_score >= POSITION_MOMENTUM_STRONG_SCORE_MIN)
        or (
            best_return is not None
            and best_return >= POSITION_MOMENTUM_STRONG_RETURN_MIN_PCT
            and minutes_strong is not None
            and minutes_strong >= return_strength_min_observations
        )
        or (minutes_strong is not None and minutes_strong >= POSITION_MOMENTUM_STRONG_MINUTES_MIN)
    )

    retained = (
        strong_seen
        and (session_score is None or session_score >= POSITION_MOMENTUM_RETAINED_MIN_SCORE)
        and (session_return is None or session_return >= POSITION_MOMENTUM_RETAINED_MIN_RETURN_PCT)
        and (session_vwap is None or session_vwap >= POSITION_MOMENTUM_RETAINED_MIN_VWAP_DIST_PCT)
    )

    broken = (
        (
            pullback_from_high is not None
            and pullback_from_high <= POSITION_MOMENTUM_BREAK_PULLBACK_PCT
        )
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
        prior_capture_peak = safe_float(sym_state.get("proactive_profit_capture_peak_pct"))
        if prior_capture_peak is not None and current_pl_pct >= prior_capture_peak + 0.75:
            sym_state.pop("proactive_profit_capture_peak_pct", None)
            sym_state.pop("proactive_profit_capture_at", None)

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
        "above_vwap_neutral",
        "fade_risk",
        "neutral_fade",
        "drift_risk",
        "late_strength",
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


def is_strong_conviction_entry(entry_ctx: dict) -> bool:
    """Return True when entry had aligned strong signals — merits looser giveback tolerance.

    Requires ALL of: mid-or-high ML bucket, strong buy-opportunity recommendation,
    opportunity score >= 10, and non-degraded setup action.  If any signal is missing
    or contradictory, conservative thresholds apply.
    """
    if not entry_ctx:
        return False

    ml_bucket = str(entry_ctx.get("entry_ml_prediction_bucket") or "").lower()
    buy_opp_rec = str(entry_ctx.get("entry_buy_opportunity_recommendation") or "").lower()
    setup_action = str(entry_ctx.get("entry_setup_policy_action") or "").lower()
    try:
        opp_score = float(entry_ctx.get("entry_buy_opportunity_score") or 0)
    except Exception:
        opp_score = 0.0

    return (
        ml_bucket in ("high_55_plus", "mid_50_55")
        and buy_opp_rec == "strong_buy_candidate"
        and opp_score >= 10
        and setup_action in ("boost", "allow")
    )


def peak_aware_breakeven_floor(peak_pl_pct: float, weak_entry: bool) -> float:
    """Dynamic breakeven floor that rises with peak P&L.

    A trade that has demonstrated real profit should not be allowed to fully
    round-trip.  For peaks below the lowest tier, returns the static flat
    floor so existing behavior is unchanged.

    Strong entries (more room):  0.30% → 0.10,  0.60% → 0.30,  1.00% → 0.45
    Weak entries (faster ratchet): 0.30% → 0.15,  0.50% → 0.35
    """
    if weak_entry:
        if peak_pl_pct >= WEAK_PEAK_LOCK_TIER2_PEAK_PCT:
            return WEAK_PEAK_LOCK_TIER2_FLOOR_PCT
        if peak_pl_pct >= WEAK_PEAK_LOCK_TIER1_PEAK_PCT:
            return WEAK_PEAK_LOCK_TIER1_FLOOR_PCT
        return WEAK_SETUP_BREAKEVEN_LOCK_FLOOR_PCT
    else:
        if peak_pl_pct >= PEAK_LOCK_TIER3_PEAK_PCT:
            return PEAK_LOCK_TIER3_FLOOR_PCT
        if peak_pl_pct >= PEAK_LOCK_TIER2_PEAK_PCT:
            return PEAK_LOCK_TIER2_FLOOR_PCT
        if peak_pl_pct >= PEAK_LOCK_TIER1_PEAK_PCT:
            return PEAK_LOCK_TIER1_FLOOR_PCT
        return BREAKEVEN_LOCK_FLOOR_PCT


def proactive_profit_capture_trigger(
    *,
    peak_pl_pct: float,
    current_pl_pct: float,
    giveback_pct: float,
    weak_entry: bool,
    retained_strength: dict | None = None,
) -> tuple[bool, str]:
    """Return whether a still-green winner should scale out before lock failure."""
    if not PROACTIVE_PROFIT_CAPTURE_ENABLED:
        return False, "proactive profit capture disabled"

    retained_strength = retained_strength or {}
    if weak_entry:
        min_peak = PROACTIVE_WEAK_MIN_PEAK_PCT
        min_current = PROACTIVE_WEAK_MIN_CURRENT_PCT
        min_giveback = PROACTIVE_WEAK_GIVEBACK_PCT
    else:
        min_peak = PROACTIVE_STRONG_MIN_PEAK_PCT
        min_current = PROACTIVE_STRONG_MIN_CURRENT_PCT
        min_giveback = PROACTIVE_STRONG_GIVEBACK_PCT

    if peak_pl_pct < min_peak:
        return False, f"peak {peak_pl_pct:.2f}% < proactive min_peak {min_peak:.2f}%"
    if current_pl_pct < min_current:
        return False, f"current {current_pl_pct:.2f}% < proactive min_current {min_current:.2f}%"
    if giveback_pct < min_giveback:
        return False, f"giveback {giveback_pct:.1f}% < proactive min_giveback {min_giveback:.1f}%"

    if (
        not weak_entry
        and retained_strength.get("retained")
        and not retained_strength.get("broken")
        and peak_pl_pct < POSITION_MANAGER_TIER2_PEAK_PCT
        and giveback_pct < POSITION_MANAGER_RETAINED_TIER2_GIVEBACK_PCT
    ):
        return (
            False,
            "retained session strength intact; "
            f"peak {peak_pl_pct:.2f}% < tier2 and giveback {giveback_pct:.1f}% "
            f"< retained threshold {POSITION_MANAGER_RETAINED_TIER2_GIVEBACK_PCT:.1f}%",
        )

    return (
        True,
        f"proactive_profit_capture: peak {peak_pl_pct:.2f}%, "
        f"current {current_pl_pct:.2f}% still >= {min_current:.2f}%, "
        f"giveback {giveback_pct:.1f}% >= {min_giveback:.1f}%, "
        f"weak_entry={weak_entry}",
    )


def exit_pattern_pressure_state(
    *,
    peak_pl_pct: float,
    current_pl_pct: float,
    giveback_pct: float,
    momentum_5m: float | None,
    momentum_15m: float | None,
    momentum_30m: float | None,
    vwap_dist_pct: float | None,
    weak_entry: bool,
    retained_strength: dict | None = None,
    entry_ctx: dict | None = None,
) -> dict:
    """Classify whether a green winner is showing failure-pattern pressure.

    This is deliberately bounded to profitable positions. It is a sell-side
    profit-capture signal, not a general exit authority.
    """
    retained_strength = retained_strength or {}
    entry_ctx = entry_ctx or {}
    adverse_signals = []
    supportive_signals = []

    if not EXIT_PATTERN_PROFIT_CAPTURE_ENABLED:
        return {
            "state": "disabled",
            "action_hint": "hold",
            "triggered": False,
            "adverse_signals": adverse_signals,
            "supportive_signals": supportive_signals,
            "reason": "exit pattern profit capture disabled",
        }

    min_peak = EXIT_PATTERN_WEAK_MIN_PEAK_PCT if weak_entry else EXIT_PATTERN_STRONG_MIN_PEAK_PCT
    min_current = (
        EXIT_PATTERN_WEAK_MIN_CURRENT_PCT if weak_entry else EXIT_PATTERN_STRONG_MIN_CURRENT_PCT
    )
    if peak_pl_pct < min_peak:
        return {
            "state": "not_armed",
            "action_hint": "hold",
            "triggered": False,
            "adverse_signals": adverse_signals,
            "supportive_signals": supportive_signals,
            "reason": f"peak {peak_pl_pct:.2f}% < exit-pattern min_peak {min_peak:.2f}%",
        }
    if current_pl_pct < min_current:
        return {
            "state": "not_armed",
            "action_hint": "hold",
            "triggered": False,
            "adverse_signals": adverse_signals,
            "supportive_signals": supportive_signals,
            "reason": f"current {current_pl_pct:.2f}% < exit-pattern min_current {min_current:.2f}%",
        }

    if momentum_5m is not None:
        if momentum_5m <= -0.10:
            adverse_signals.append(f"5m_rollover={momentum_5m:.2f}%")
        elif momentum_5m >= 0.10:
            supportive_signals.append(f"5m_support={momentum_5m:.2f}%")
    if momentum_15m is not None:
        if momentum_15m <= -0.05:
            adverse_signals.append(f"15m_rollover={momentum_15m:.2f}%")
        elif momentum_15m >= 0.10:
            supportive_signals.append(f"15m_support={momentum_15m:.2f}%")
    if momentum_30m is not None:
        if momentum_30m <= -0.10:
            adverse_signals.append(f"30m_rollover={momentum_30m:.2f}%")
        elif momentum_30m >= 0.15:
            supportive_signals.append(f"30m_support={momentum_30m:.2f}%")
    if vwap_dist_pct is not None:
        if vwap_dist_pct <= -0.05:
            adverse_signals.append(f"vwap_loss={vwap_dist_pct:.2f}%")
        elif vwap_dist_pct >= 0.10:
            supportive_signals.append(f"above_vwap={vwap_dist_pct:.2f}%")
    if retained_strength.get("broken"):
        adverse_signals.append("retained_session_strength_broken")
    elif retained_strength.get("retained"):
        supportive_signals.append("retained_session_strength")

    ml_bucket = str(entry_ctx.get("entry_ml_prediction_bucket") or "").lower()
    if ml_bucket == "weak_below_45" and giveback_pct >= EXIT_PATTERN_WEAK_GIVEBACK_PCT:
        adverse_signals.append(f"weak_ml_bucket_giveback={giveback_pct:.1f}%")
    if weak_entry and giveback_pct >= EXIT_PATTERN_WEAK_GIVEBACK_PCT:
        adverse_signals.append(f"weak_entry_giveback={giveback_pct:.1f}%")

    required = EXIT_PATTERN_MIN_ADVERSE_SIGNALS
    if weak_entry:
        required = max(1, required - 1)
    if retained_strength.get("retained") and not retained_strength.get("broken"):
        required += 1

    triggered = len(adverse_signals) >= required
    state = "profit_failure_pressure" if triggered else "monitor"
    action_hint = "sell_partial" if triggered else "hold"
    reason = (
        f"exit_pattern_pressure: adverse={len(adverse_signals)} required={required}; "
        f"signals={', '.join(adverse_signals) or '-'}; "
        f"support={', '.join(supportive_signals) or '-'}; "
        f"weak_entry={weak_entry}"
    )
    return {
        "state": state,
        "action_hint": action_hint,
        "triggered": triggered,
        "required_adverse_signals": required,
        "adverse_signals": adverse_signals,
        "supportive_signals": supportive_signals,
        "reason": reason,
    }


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

    if is_high_confidence_auto_buy_entry(entry_ctx):
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
    auto_buy_hold = auto_buy_min_hold_state(entry_ctx, current_pl_pct)
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
        reasons.append(
            f"loss {current_pl_pct:.2f}% <= full-exit threshold {FULL_EXIT_LOSS_PCT:.2f}%"
        )

    if (
        action == "hold"
        and vwap_dist_pct is not None
        and current_pl_pct < 0
        and vwap_dist_pct <= VWAP_LOSS_EXIT_PCT
    ):
        action = "sell_full"
        sell_fraction = 1.0
        severity = "high"
        reasons.append(f"red position below VWAP by {vwap_dist_pct:.2f}%")

    if action == "hold" and momentum_5m is not None and momentum_15m is not None:
        if current_pl_pct < 0 and momentum_5m < -0.20 and momentum_15m < -0.30:
            action = "sell_full"
            sell_fraction = 1.0
            severity = "high"
            reasons.append(
                f"red position with falling 5m/15m momentum ({momentum_5m:.2f}%, {momentum_15m:.2f}%)"
            )

    # Full exit: breakeven/profit-lock protection.
    # If a position has already moved favorably enough, do not allow it to
    # round-trip back to breakeven/red, especially for weaker entry contexts.
    raw_weak_entry_context = is_weak_entry_context(entry_ctx)
    weak_entry_context = raw_weak_entry_context
    if is_high_confidence_auto_buy_entry(entry_ctx):
        weak_entry_context = False

    # Three-tier quality-split thresholds:
    #   strong_conviction: all signals aligned → most room (70% giveback, 1.0% min)
    #   normal strong:     standard room (60% giveback, 0.75% min)
    #   weak:              managed tightly (35% giveback, 0.35% min)
    # is_strong_conviction_entry is only evaluated when entry is NOT already weak.
    strong_conviction_entry = (
        is_strong_conviction_entry(entry_ctx) if not weak_entry_context else False
    )

    if strong_conviction_entry:
        giveback_trigger_pct = STRONG_CONVICTION_PROFIT_GIVEBACK_TRIGGER_PCT  # 70%
        min_profit_partial_pct = STRONG_CONVICTION_MIN_PROFIT_PARTIAL_PCT  # 1.0%
    elif weak_entry_context:
        giveback_trigger_pct = WEAK_ENTRY_PROFIT_GIVEBACK_TRIGGER_PCT  # 35%
        min_profit_partial_pct = WEAK_ENTRY_MIN_PROFIT_PARTIAL_PCT  # 0.35%
    else:
        giveback_trigger_pct = STRONG_ENTRY_PROFIT_GIVEBACK_TRIGGER_PCT  # 60%
        min_profit_partial_pct = MIN_PROFIT_PARTIAL_PCT  # 0.75%

    # Peak-aware breakeven lock:
    # Trigger arms at the lowest tier (0.30%) — closes the gap where trades
    # peaking between 0.30% and 0.50% had no protection.  The floor rises with
    # the peak so a trade that already showed +0.70% cannot round-trip to zero.
    # hard_full_exit = True prevents the continuation-delay check from
    # overriding this protection on subsequent position-manager cycles.
    breakeven_trigger = (
        WEAK_PEAK_LOCK_TIER1_PEAK_PCT  # 0.30 — lowest weak tier
        if weak_entry_context
        else PEAK_LOCK_TIER1_PEAK_PCT  # 0.30 — lowest strong tier
    )
    breakeven_floor = peak_aware_breakeven_floor(peak_pl_pct, weak_entry_context)

    proactive_capture, proactive_reason = proactive_profit_capture_trigger(
        peak_pl_pct=peak_pl_pct,
        current_pl_pct=current_pl_pct,
        giveback_pct=giveback_pct,
        weak_entry=weak_entry_context,
        retained_strength=retained_strength,
    )
    exit_pattern_pressure = exit_pattern_pressure_state(
        peak_pl_pct=peak_pl_pct,
        current_pl_pct=current_pl_pct,
        giveback_pct=giveback_pct,
        momentum_5m=momentum_5m,
        momentum_15m=momentum_15m,
        momentum_30m=momentum_30m,
        vwap_dist_pct=vwap_dist_pct,
        weak_entry=weak_entry_context,
        retained_strength=retained_strength,
        entry_ctx=entry_ctx,
    )
    sym_state = state.setdefault(symbol, {})
    prior_proactive_peak = safe_float(sym_state.get("proactive_profit_capture_peak_pct"))
    if proactive_capture and prior_proactive_peak is not None:
        proactive_capture = False
        proactive_reason = (
            f"proactive profit already captured at peak {prior_proactive_peak:.2f}%; "
            "waiting for materially higher peak before another proactive partial"
        )
    if action == "hold" and proactive_capture:
        action = "sell_partial"
        sell_fraction = PARTIAL_SELL_PCT
        severity = "medium"
        sym_state["proactive_profit_capture_peak_pct"] = round(peak_pl_pct, 4)
        sym_state["proactive_profit_capture_at"] = datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S")
        reasons.append(proactive_reason)

    if action == "hold" and exit_pattern_pressure.get("triggered"):
        action = "sell_partial"
        sell_fraction = PARTIAL_SELL_PCT
        severity = "medium"
        reasons.append(exit_pattern_pressure["reason"])

    if action == "hold" and peak_pl_pct >= breakeven_trigger and current_pl_pct <= breakeven_floor:
        action = "sell_full"
        sell_fraction = 1.0
        severity = "high"
        hard_full_exit = True
        reasons.append(
            f"peak_aware_breakeven_lock: peak {peak_pl_pct:.2f}% >= "
            f"tier_min {breakeven_trigger:.2f}%, current {current_pl_pct:.2f}% <= "
            f"floor {breakeven_floor:.2f}%, weak_entry={weak_entry_context}"
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
    # Thresholds are quality-split: weak entries get tighter giveback and
    # take partials earlier; strong entries get more room.
    if (
        action == "hold"
        and peak_pl_pct >= min_profit_partial_pct
        and giveback_pct >= giveback_trigger_pct
    ):
        action = "sell_partial"
        sell_fraction = PARTIAL_SELL_PCT
        severity = "medium"
        reasons.append(
            f"profit giveback {giveback_pct:.1f}% from peak {peak_pl_pct:.2f}% "
            f"after reaching min profit {min_profit_partial_pct:.2f}% "
            f"(weak_entry={weak_entry_context})"
        )

    if action == "hold" and current_pl_pct >= min_profit_partial_pct:
        if (
            momentum_5m is not None
            and momentum_15m is not None
            and momentum_5m < -0.15
            and momentum_15m < 0
        ):
            action = "sell_partial"
            sell_fraction = PARTIAL_SELL_PCT
            severity = "medium"
            reasons.append(
                f"profitable but momentum fading ({momentum_5m:.2f}%, {momentum_15m:.2f}%); "
                f"min_profit={min_profit_partial_pct:.2f}% weak_entry={weak_entry_context}"
            )

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
        and not weak_entry_context  # weak entries: take profits when they appear, no delay
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

    if auto_buy_hold.get("active") and action in ("sell_partial", "sell_full"):
        original_action = action
        original_severity = severity
        action = "hold"
        sell_fraction = 0.0
        severity = "watch"
        hard_full_exit = False
        reasons.append(
            f"{auto_buy_hold['reason']}; suppressed {original_action} "
            f"(original_severity={original_severity}) during fresh auto-buy entry window"
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
        "exit_pattern_pressure": exit_pattern_pressure,
        "auto_buy_min_hold": auto_buy_hold,
        "weak_entry_context": weak_entry_context,
        "raw_weak_entry_context": raw_weak_entry_context,
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

        order_id = order.get("order_id") or order.get("id") or getattr(order, "id", None)
        status = order.get("status") or getattr(order, "status", None) or "submitted"
        qty = order.get("qty") or getattr(order, "qty", None) or decision.get("sell_qty")

        reason = (
            f"{exit_type}: "
            f"action={decision.get('action')} "
            f"severity={decision.get('severity')} "
            f"reasons={'; '.join(decision.get('reasons') or [])}"
        )

        position_repo.insert_position_manager_exit(
            timestamp=datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S"),
            symbol=decision.get("symbol"),
            signal_price=decision.get("current_price"),
            reason=reason,
            confidence="position_manager",
            order_id=order_id,
            order_status=status,
            qty=int(float(qty)) if qty is not None else None,
            entry_context=decision.get("entry_context") or {},
            momentum_direction="falling"
            if (
                (
                    decision.get("momentum_5m_pct") is not None
                    and decision.get("momentum_5m_pct") < 0
                )
                or (
                    decision.get("momentum_15m_pct") is not None
                    and decision.get("momentum_15m_pct") < 0
                )
            )
            else "neutral",
            momentum_pct=decision.get("momentum_5m_pct"),
        )

        return True

    except Exception as e:
        print(f"[WARN] Failed to log position-manager exit to trades.db: {e}")
        return False


def _open_orders_cleared(broker_service, symbol) -> bool:
    """Poll until canceled open orders clear so Alpaca releases the held shares.

    Returns True once no open orders remain for the symbol (so a partial market
    sell can be submitted in the same pass), or False if they do not clear within
    the bounded poll window.
    """
    for _ in range(_PARTIAL_CANCEL_POLL_ATTEMPTS):
        if not broker_service.list_open_orders(symbol):
            return True
        time.sleep(_PARTIAL_CANCEL_POLL_DELAY_SEC)
    return not broker_service.list_open_orders(symbol)


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
        order = broker_service.place_order(symbol, "sell", 0, 0, 0)
        return {"submitted": bool(order), "order": order}

    if action == "sell_partial":
        sell_qty = planned_partial_sell_qty(qty, decision.get("sell_fraction"))
        if sell_qty < 1:
            if not PROMOTE_UNEXECUTABLE_PARTIALS:
                return {"submitted": False, "reason": "partial sell qty < 1"}
            order = broker_service.place_order(symbol, "sell", 0, 0, 0)
            return {
                "submitted": bool(order),
                "order": order,
                "promoted_action": "sell_full",
                "reason": "partial sell qty < 1; promoted to full exit",
            }

        open_orders = broker_service.list_open_orders(symbol)
        for o in open_orders:
            broker_service.cancel_order(o.id)
        if open_orders and not _open_orders_cleared(broker_service, symbol):
            # Only defer if cancellation genuinely did not settle within the poll
            # window (rare). Otherwise fall through and sell in this same pass so the
            # position is not left with canceled brackets AND no exit until the next
            # cron cycle. The submit below still fails closed on any residual
            # available-quantity error.
            return {
                "submitted": False,
                "reason": (
                    f"canceled {len(open_orders)} open order(s) but they did not "
                    "clear within the poll window; deferring partial exit"
                ),
            }

        try:
            order = broker_service.submit_market_sell(symbol, sell_qty)
        except Exception as exc:
            return {
                "submitted": False,
                "reason": f"partial sell submit failed: {exc}",
            }

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
    parser.add_argument(
        "--live", action="store_true", help="Allow live sells if POSITION_MANAGER_LIVE_SELLS=true"
    )
    args = parser.parse_args()

    state = load_state()

    try:
        positions = broker_service.list_positions()
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
    print(f"rows_written: {len(decisions)}")

    if args.json:
        print(json.dumps(decisions, indent=2, sort_keys=True))
    else:
        render(decisions)

    if args.live:
        if not LIVE_SELLS:
            print()
            print(
                "Live mode requested, but POSITION_MANAGER_LIVE_SELLS is not true. No orders submitted."
            )
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
                    decision="submitted"
                    if isinstance(result, dict) and result.get("submitted")
                    else "not_submitted",
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
