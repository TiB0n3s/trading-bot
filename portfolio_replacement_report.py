#!/usr/bin/env python3
"""
Portfolio Replacement Report

Read-only intelligence report for full-portfolio situations.

Purpose:
- Review recent BUY signals for strongest performance potential
- Identify top candidates blocked by macro_position_limit
- Compare candidates against weakest current Alpaca holdings
- Recommend observe_only / replacement_candidate / extra_slot_candidate

This does not place, cancel, or modify orders.
"""

import argparse
import json
from datetime import datetime, timedelta
from collections import defaultdict
from pathlib import Path

import pytz

from services.broker_service import broker_service
from db import DB_PATH, get_connection
from bot_events import log_event
from policy_artifacts import atomic_write_json


ET = pytz.timezone("America/New_York")
BASE_DIR = Path(__file__).resolve().parent
PORTFOLIO_REPLACEMENT_MEMORY_FILE = BASE_DIR / "portfolio_replacement_memory.json"


STRONG_BUY_RECS = {"strong_buy_candidate", "buy_candidate"}
STRONG_SESSION_LABELS = {"strong_uptrend", "developing_uptrend"}
WEAK_SESSION_LABELS = {"fading", "rangebound", "reversal_attempt", "weak", "downtrend", "bearish"}


def to_float(v, default=None):
    try:
        if v is None:
            return default
        return float(v)
    except Exception:
        return default


def category(reason):
    if not reason:
        return "approved"
    if ":" in reason:
        return reason.split(":", 1)[0].strip()
    return "uncategorized"


def get_positions():
    rows = []
    try:
        positions = broker_service.list_positions()
    except Exception as e:
        return [], f"failed to fetch Alpaca positions: {e}"

    for p in positions:
        rows.append({
            "symbol": p.symbol,
            "qty": to_float(p.qty, 0),
            "market_value": to_float(p.market_value, 0),
            "unrealized_pl": to_float(p.unrealized_pl, 0),
            "unrealized_plpc": to_float(p.unrealized_plpc, 0) * 100.0,
            "avg_entry_price": to_float(p.avg_entry_price, 0),
            "current_price": to_float(p.current_price, 0),
        })

    return rows, None


def load_recent_buy_signals(minutes=90, limit=300):
    since = datetime.now(ET) - timedelta(minutes=minutes)
    since_s = since.strftime("%Y-%m-%d %H:%M:%S")

    with get_connection(DB_PATH) as con:
        rows = con.execute("""
            SELECT
                id,
                timestamp,
                symbol,
                action,
                signal_price,
                approved,
                rejection_reason,

                market_bias,
                market_bias_effective,
                fundamental_score,
                risk_level,
                entry_quality,
                trend_direction,
                trend_strength,
                momentum_direction,
                momentum_pct,

                session_trend_label,
                session_trend_score,
                session_return_pct,
                session_momentum_5m_pct,
                session_momentum_15m_pct,
                session_momentum_30m_pct,
                session_distance_from_vwap_pct,

                prediction_score,
                prediction_decision,

                setup_label,
                setup_policy_action,
                setup_size_multiplier,

                buy_opportunity_score,
                buy_opportunity_recommendation,
                buy_opportunity_reason
            FROM trades
            WHERE LOWER(action) = 'buy'
              AND timestamp >= ?
              AND signal_price IS NOT NULL
            ORDER BY id DESC
            LIMIT ?
        """, (since_s, limit)).fetchall()

    return rows


def score_signal(row, held_symbols):
    """
    Rank a signal's relative opportunity strength using persisted intelligence fields.
    Uses the existing 0-16-ish buy_opportunity_score scale if present.
    """
    score = 0.0
    reasons = []

    buy_score = to_float(row["buy_opportunity_score"], 0)
    score += buy_score * 5.0
    if buy_score:
        reasons.append(f"buy_score={buy_score:g}")

    rec = row["buy_opportunity_recommendation"]
    if rec == "strong_buy_candidate":
        score += 25
        reasons.append("strong_buy_candidate")
    elif rec == "buy_candidate":
        score += 15
        reasons.append("buy_candidate")
    elif rec == "small_buy_candidate":
        score += 5
        reasons.append("small_buy_candidate")
    elif rec == "watch":
        score -= 5
        reasons.append("watch")
    elif rec == "avoid":
        score -= 30
        reasons.append("avoid")

    session = row["session_trend_label"]
    session_score = to_float(row["session_trend_score"], 0)
    if session == "strong_uptrend":
        score += 20
        reasons.append("strong_session")
    elif session == "developing_uptrend":
        score += 12
        reasons.append("developing_session")
    elif session in WEAK_SESSION_LABELS:
        score -= 12
        reasons.append(f"weak_session={session}")

    if session_score:
        score += max(-10, min(10, session_score))

    setup_action = row["setup_policy_action"]
    setup_label = row["setup_label"]
    if setup_action == "boost":
        score += 15
        reasons.append(f"setup_boost={setup_label}")
    elif setup_action == "neutral":
        score += 0
    elif setup_action in ("block", "avoid"):
        score -= 35
        reasons.append(f"setup_{setup_action}={setup_label}")

    pred_decision = row["prediction_decision"]
    pred_score = to_float(row["prediction_score"], None)
    if pred_decision == "pass":
        score += 8
        reasons.append("prediction_pass")
    elif pred_decision == "watch":
        score -= 4
        reasons.append("prediction_watch")
    elif pred_decision == "block":
        score -= 25
        reasons.append("prediction_block")

    if pred_score is not None:
        score += max(-8, min(8, pred_score - 5))

    momentum_direction = row["momentum_direction"]
    momentum_pct = to_float(row["momentum_pct"], 0)
    if momentum_direction == "rising":
        score += 8
        reasons.append("momentum_rising")
    elif momentum_direction == "falling":
        score -= 12
        reasons.append("momentum_falling")

    if momentum_pct:
        score += max(-8, min(8, momentum_pct * 10))

    effective_bias = row["market_bias_effective"] or row["market_bias"]
    if effective_bias in ("buy", "live_override_buy"):
        score += 8
        reasons.append(f"bias={effective_bias}")
    elif effective_bias in ("avoid_hard", "avoid_soft", "avoid", "live_override_neutral"):
        score -= 20
        reasons.append(f"bias={effective_bias}")

    risk_level = row["risk_level"]
    if risk_level == "very_high":
        score -= 10
        reasons.append("very_high_risk")
    elif risk_level == "high":
        score -= 5
        reasons.append("high_risk")

    entry_quality = row["entry_quality"]
    if entry_quality in ("do_not_chase", "avoid_chasing", "poor"):
        score -= 20
        reasons.append(f"entry_quality={entry_quality}")

    symbol = row["symbol"]
    if symbol in held_symbols:
        score -= 25
        reasons.append("already_held")

    return round(score, 2), reasons


def weakest_holding(positions):
    if not positions:
        return None
    return sorted(positions, key=lambda p: p["unrealized_plpc"])[0]


def evaluate_candidate(row, score, positions, held_symbols):
    weakest = weakest_holding(positions)
    rejection_cat = category(row["rejection_reason"])
    symbol = row["symbol"]

    buy_score = to_float(row["buy_opportunity_score"], 0)
    rec = row["buy_opportunity_recommendation"]
    session = row["session_trend_label"]
    setup_action = row["setup_policy_action"]

    if symbol in held_symbols:
        return "observe_only", "candidate already held"

    if rejection_cat != "macro_position_limit":
        return "observe_only", f"not a macro_position_limit block ({rejection_cat})"

    if not weakest:
        return "observe_only", "no current holdings to compare"

    weak_plpc = weakest["unrealized_plpc"]

    candidate_strong = (
        buy_score >= 14
        and rec == "strong_buy_candidate"
        and session in STRONG_SESSION_LABELS
        and setup_action in ("boost", "neutral", None)
    )

    candidate_premium = (
        buy_score >= 15
        and rec == "strong_buy_candidate"
        and session == "strong_uptrend"
        and setup_action == "boost"
    )

    if candidate_premium and weak_plpc <= -1.00:
        return (
            "replace_now_candidate",
            f"premium candidate vs weak holding {weakest['symbol']} {weak_plpc:.2f}%"
        )

    if candidate_strong and weak_plpc <= -0.50:
        return (
            "replacement_candidate",
            f"strong candidate vs weakest holding {weakest['symbol']} {weak_plpc:.2f}%"
        )

    if candidate_premium and weak_plpc >= 0 and weak_plpc < 0.25:
        return (
            "extra_slot_candidate",
            f"premium candidate but weakest holding {weakest['symbol']} only {weak_plpc:.2f}%"
        )

    if candidate_strong:
        return (
            "observe_only",
            f"candidate strong but weakest holding {weakest['symbol']} only {weak_plpc:.2f}%"
        )

    return "observe_only", "candidate not strong enough for replacement"


def dedupe_best_by_symbol(scored_rows):
    best = {}
    for item in scored_rows:
        sym = item["symbol"]
        if sym not in best or item["score"] > best[sym]["score"]:
            best[sym] = item
    return sorted(best.values(), key=lambda x: x["score"], reverse=True)



def build_replacement_memory(positions, weakest, best, candidates, minutes):
    """Build machine-readable portfolio replacement intelligence."""
    top_candidates = []
    for item in best[:20]:
        top_candidates.append({
            "symbol": item.get("symbol"),
            "score": item.get("score"),
            "decision": item.get("decision"),
            "decision_reason": item.get("decision_reason"),
            "approved": item.get("approved"),
            "rejection_category": item.get("rejection_category"),
            "buy_opportunity_score": item.get("buy_opportunity_score"),
            "buy_opportunity_recommendation": item.get("buy_opportunity_recommendation"),
            "session_trend_label": item.get("session_trend_label"),
            "session_trend_score": item.get("session_trend_score"),
            "setup_label": item.get("setup_label"),
            "setup_policy_action": item.get("setup_policy_action"),
            "prediction_score": item.get("prediction_score"),
            "prediction_decision": item.get("prediction_decision"),
            "market_bias_effective": item.get("market_bias_effective"),
            "reasons": item.get("reasons") or [],
        })

    replacement_candidates = []
    for item in candidates:
        replacement_candidates.append({
            "symbol": item.get("symbol"),
            "score": item.get("score"),
            "decision": item.get("decision"),
            "decision_reason": item.get("decision_reason"),
            "buy_opportunity_score": item.get("buy_opportunity_score"),
            "buy_opportunity_recommendation": item.get("buy_opportunity_recommendation"),
            "session_trend_label": item.get("session_trend_label"),
            "setup_label": item.get("setup_label"),
            "setup_policy_action": item.get("setup_policy_action"),
            "prediction_score": item.get("prediction_score"),
            "prediction_decision": item.get("prediction_decision"),
        })

    if replacement_candidates:
        strongest = replacement_candidates[0]
        recommendation = strongest.get("decision") or "replacement_candidate"
        reason = strongest.get("decision_reason") or "replacement candidate found"
    elif top_candidates:
        strongest = top_candidates[0]
        recommendation = "observe_only"
        reason = strongest.get("decision_reason") or "no replacement candidate met strict criteria"
    else:
        strongest = None
        recommendation = "observe_only"
        reason = "no recent buy candidates found"

    return {
        "generated_at": datetime.now(ET).strftime("%Y-%m-%d %H:%M:%S"),
        "lookback_minutes": minutes,
        "open_position_count": len(positions),
        "weakest_holding": weakest,
        "recommendation": recommendation,
        "reason": reason,
        "strongest_candidate": strongest,
        "top_candidates": top_candidates,
        "replacement_candidates": replacement_candidates,
        "mode": "observe_only",
        "notes": "This memory is advisory only. It does not authorize macro override, auto-rotation, or extra position slots.",
    }


def write_replacement_memory(memory):
    atomic_write_json(PORTFOLIO_REPLACEMENT_MEMORY_FILE, memory)
    print(f"Wrote {PORTFOLIO_REPLACEMENT_MEMORY_FILE}")
    return memory

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--minutes", type=int, default=90)
    parser.add_argument("--limit", type=int, default=300)
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--write-memory", action="store_true", help="Write portfolio_replacement_memory.json")
    args = parser.parse_args()

    print("=" * 96)
    print("  Portfolio Replacement / Strongest Signal Report")
    print("=" * 96)

    positions, err = get_positions()
    if err:
        print(f"ERROR: {err}")
        return

    held_symbols = {p["symbol"] for p in positions}
    weakest = weakest_holding(positions)

    print()
    print(f"Open positions: {len(positions)}")
    if positions:
        print(f"{'Sym':<6} {'Qty':>6} {'Value':>10} {'P&L$':>10} {'P&L%':>8}")
        print(f"{'-'*6} {'-'*6} {'-'*10} {'-'*10} {'-'*8}")
        for p in sorted(positions, key=lambda x: x["unrealized_plpc"]):
            print(
                f"{p['symbol']:<6} {p['qty']:>6.0f} "
                f"${p['market_value']:>9.2f} "
                f"${p['unrealized_pl']:>+9.2f} "
                f"{p['unrealized_plpc']:>7.2f}%"
            )

    if weakest:
        print()
        print(
            f"Weakest holding: {weakest['symbol']} "
            f"P&L={weakest['unrealized_plpc']:.2f}% "
            f"(${weakest['unrealized_pl']:+.2f})"
        )

    rows = load_recent_buy_signals(minutes=args.minutes, limit=args.limit)
    scored = []

    for r in rows:
        score, reasons = score_signal(r, held_symbols)
        decision, reason = evaluate_candidate(r, score, positions, held_symbols)

        scored.append({
            "id": r["id"],
            "timestamp": r["timestamp"],
            "symbol": r["symbol"],
            "approved": r["approved"],
            "rejection_category": category(r["rejection_reason"]),
            "rejection_reason": r["rejection_reason"],
            "score": score,
            "decision": decision,
            "decision_reason": reason,
            "buy_opportunity_score": r["buy_opportunity_score"],
            "buy_opportunity_recommendation": r["buy_opportunity_recommendation"],
            "session_trend_label": r["session_trend_label"],
            "session_trend_score": r["session_trend_score"],
            "setup_label": r["setup_label"],
            "setup_policy_action": r["setup_policy_action"],
            "prediction_score": r["prediction_score"],
            "prediction_decision": r["prediction_decision"],
            "market_bias_effective": r["market_bias_effective"] or r["market_bias"],
            "reasons": reasons,
        })

    best = dedupe_best_by_symbol(scored)

    print()
    print(f"Recent BUY signals reviewed: {len(rows)} over last {args.minutes} minutes")
    print()
    print("Top strongest signals by symbol:")
    print(
        f"{'Sym':<6} {'Score':>7} {'Decision':<24} {'BuyScore':>8} {'BuyRec':<22} "
        f"{'Session':<20} {'Setup':<34} {'Pred':<12} Reason"
    )
    print("-" * 180)

    for item in best[:args.top]:
        print(
            f"{item['symbol']:<6} "
            f"{item['score']:>7.1f} "
            f"{item['decision']:<24} "
            f"{str(item['buy_opportunity_score']):>8} "
            f"{str(item['buy_opportunity_recommendation']):<22} "
            f"{str(item['session_trend_label']):<20} "
            f"{str(item['setup_label'])[:24] + '/' + str(item['setup_policy_action']):<34} "
            f"{str(item['prediction_score']) + '/' + str(item['prediction_decision']):<12} "
            f"{item['decision_reason']}"
        )

    print()
    print("Replacement / expansion candidates:")
    candidates = [
        x for x in best
        if x["decision"] in ("replacement_candidate", "replace_now_candidate", "extra_slot_candidate")
    ]

    if not candidates:
        print("  None. Current recommendation: respect macro position limit / observe only.")
    else:
        for c in candidates:
            print(
                f"  {c['symbol']}: {c['decision']} "
                f"score={c['score']} buy_score={c['buy_opportunity_score']} "
                f"reason={c['decision_reason']}"
            )

    if args.write_memory:
        memory = build_replacement_memory(
            positions=positions,
            weakest=weakest,
            best=best,
            candidates=candidates,
            minutes=args.minutes,
        )
        write_replacement_memory(memory)

        log_event(
            event_type="PORTFOLIO_REPLACEMENT",
            symbol=(memory.get("strongest_candidate") or {}).get("symbol"),
            action="review_replacement",
            decision=memory.get("recommendation"),
            severity="info",
            reason=memory.get("reason"),
            source="portfolio_replacement_report.py",
            payload=memory,
        )


if __name__ == "__main__":
    main()
