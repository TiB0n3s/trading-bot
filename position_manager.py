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


BASE_DIR = Path(__file__).resolve().parent
STATE_FILE = BASE_DIR / "position_manager_state.json"
ET = pytz.timezone("America/New_York")


LIVE_SELLS = os.getenv("POSITION_MANAGER_LIVE_SELLS", "false").lower() in ("1", "true", "yes", "on")
PARTIAL_SELL_PCT = float(os.getenv("POSITION_MANAGER_PARTIAL_SELL_PCT", "0.50"))
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
                    buy_opportunity_score, buy_opportunity_recommendation
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
            "open_lot_qty": lots[0]["remaining"],
        }

    except Exception as e:
        return {"entry_context_error": str(e)}


def fetch_intraday_bars(symbol, minutes=60):
    start = (now_utc() - timedelta(minutes=minutes + 5)).isoformat()
    bars = list(api.get_bars(symbol, "1Min", start=start, feed="iex"))

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

    setup_label = str(entry_ctx.get("setup_label") or "").lower()
    prediction_decision = str(entry_ctx.get("prediction_decision") or "").lower()
    buy_rec = str(entry_ctx.get("buy_opportunity_recommendation") or "").lower()
    entry_quality = str(entry_ctx.get("entry_quality") or "").lower()

    weak_tokens = (
        "fade_risk",
        "neutral_fade",
        "drift_risk",
        "unclassified",
    )

    if any(token in setup_label for token in weak_tokens):
        return True

    if prediction_decision in ("watch", "caution"):
        return True

    if buy_rec in ("small_buy_candidate", "watch"):
        return True

    if entry_quality in ("tactical_only", "conditional", "avoid_chasing", "do_not_chase"):
        return True

    return False


def evaluate_position(position, state):
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

    current_pl_pct = peak["current_pl_pct"]
    giveback_pct = peak["giveback_pct"]
    peak_pl_pct = peak["peak_pl_pct"]

    # Full exit: losing and momentum/VWAP deteriorating.
    if current_pl_pct <= FULL_EXIT_LOSS_PCT:
        action = "sell_full"
        sell_fraction = 1.0
        severity = "high"
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

    if not reasons:
        reasons.append("no exit trigger")

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
        sell_qty = int(qty * float(decision.get("sell_fraction") or PARTIAL_SELL_PCT))
        if sell_qty < 1:
            return {"submitted": False, "reason": "partial sell qty < 1"}

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

    decisions = [evaluate_position(p, state) for p in positions]
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
