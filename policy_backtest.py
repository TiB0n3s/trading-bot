#!/usr/bin/env python3
"""
Policy Backtest

Read-only replay of historical BUY rows using the current decision-policy style.

Purpose:
- Estimate how the new executive policy would have treated past signals
- Compare policy decisions against actual approved/rejected outcomes
- Highlight where policy may be too strict or too loose

This does not place, cancel, or modify orders.
"""

import argparse
import json
import statistics
from collections import defaultdict
from datetime import date, timedelta, datetime
from pathlib import Path

from db import DB_PATH, get_connection

BASE_DIR = Path(__file__).resolve().parent
POLICY_BACKTEST_SUMMARY_FILE = BASE_DIR / "policy_backtest_summary.json"


def category(reason):
    if not reason:
        return "approved"
    if ":" in reason:
        return reason.split(":", 1)[0].strip()
    return "uncategorized"


def score_to_100(value):
    try:
        if value is None:
            return None
        v = float(value)
        return v * 10 if v <= 10 else v
    except Exception:
        return None


def policy_replay(row):
    """
    Approximate current decision-policy behavior from stored DB columns.

    This is intentionally conservative and deterministic.
    """
    reasons = []
    supports = []
    risks = []

    symbol = row["symbol"]
    approved = int(row["approved"] or 0) == 1
    reject_cat = category(row["rejection_reason"])

    opp_score = score_to_100(row["buy_opportunity_score"])
    opp_rec = row["buy_opportunity_recommendation"]

    pred_score = row["prediction_score"]
    pred_decision = row["prediction_decision"]

    setup_label = row["setup_label"]
    setup_policy = row["setup_policy_action"]

    session_label = row["session_trend_label"]
    session_score = row["session_trend_score"]

    bias = row["market_bias"]
    effective_bias = row["market_bias_effective"] or bias

    risk_level = row["risk_level"]
    entry_quality = row["entry_quality"]
    momentum_direction = row["momentum_direction"]

    # Support/risk evidence.
    if effective_bias in ("buy", "live_override_buy"):
        supports.append(f"bias={effective_bias}")
    elif effective_bias in ("avoid", "avoid_soft", "avoid_hard", "live_override_neutral"):
        risks.append(f"bias={effective_bias}")

    if pred_decision == "block":
        risks.append("prediction=block")
    elif pred_decision == "watch":
        risks.append("prediction=watch")
    elif pred_decision in ("allow", "pass", "buy"):
        supports.append(f"prediction={pred_decision}")

    if setup_policy in ("block", "avoid"):
        risks.append(f"setup_policy={setup_policy}")
    elif setup_policy in ("allow", "favor"):
        supports.append(f"setup_policy={setup_policy}")

    if opp_rec in ("avoid",):
        risks.append(f"buy_opportunity={opp_rec}")
    elif opp_rec in ("watch", "small_buy_candidate"):
        risks.append(f"buy_opportunity={opp_rec}")
    elif opp_rec in ("buy_candidate", "strong_buy_candidate"):
        supports.append(f"buy_opportunity={opp_rec}")

    if session_label in ("downtrend", "bearish", "weak"):
        risks.append(f"session={session_label}")
    elif session_label in ("uptrend", "strong_uptrend", "bullish"):
        supports.append(f"session={session_label}")

    if momentum_direction == "falling":
        risks.append("momentum=falling")
    elif momentum_direction == "rising":
        supports.append("momentum=rising")

    if risk_level == "very_high":
        risks.append("risk_level=very_high")

    if entry_quality in ("do_not_chase", "avoid_chasing", "poor"):
        risks.append(f"entry_quality={entry_quality}")

    # Policy decision approximation.
    decision = "allow"
    size_multiplier = 1.0

    # Hard blocks.
    if pred_decision == "block":
        decision = "block"
        reasons.append("prediction block")

    if setup_policy in ("block", "avoid"):
        decision = "block"
        reasons.append("setup policy block")

    if effective_bias == "avoid_hard":
        decision = "block"
        reasons.append("hard avoid bias")

    if opp_rec == "avoid" and opp_score is not None and opp_score < 40:
        decision = "block"
        reasons.append("low opportunity avoid")

    # Score-based blocks.
    if decision != "block":
        if opp_score is not None and opp_score < 40:
            decision = "block"
            reasons.append(f"opportunity score {opp_score:.1f} < 40")

    # Size-down / caution.
    if decision != "block":
        if opp_score is not None and opp_score < 55:
            decision = "size_down"
            size_multiplier = 0.50
            reasons.append(f"opportunity score {opp_score:.1f} < 55")
        elif len(risks) >= 3:
            decision = "size_down"
            size_multiplier = 0.50
            reasons.append("3+ risk signals")
        elif len(risks) >= 2:
            decision = "size_down"
            size_multiplier = 0.75
            reasons.append("2 risk signals")

    return {
        "symbol": symbol,
        "actual_approved": approved,
        "actual_rejection_category": reject_cat,
        "policy_decision": decision,
        "size_multiplier": size_multiplier,
        "policy_reason": "; ".join(reasons) or "policy allows",
        "supports": supports,
        "risks": risks,
        "opportunity_score_100": opp_score,
        "buy_opportunity_recommendation": opp_rec,
        "prediction_decision": pred_decision,
        "setup_label": setup_label,
        "setup_policy_action": setup_policy,
        "session_trend_label": session_label,
    }


def load_rows(args):
    params = []
    extra = ""

    if args.all:
        pass
    elif args.week:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        saturday = monday + timedelta(days=5)
        extra += " AND timestamp >= ? AND timestamp < ?"
        params.extend([monday.isoformat(), saturday.isoformat()])
    else:
        target = args.date or date.today().isoformat()
        extra += " AND timestamp LIKE ?"
        params.append(f"{target}%")

    if args.symbol:
        extra += " AND symbol = ?"
        params.append(args.symbol.upper())

    params.append(args.limit)

    with get_connection(DB_PATH) as con:
        rows = con.execute(f"""
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
                risk_level,
                entry_quality,
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
            FROM trades
            WHERE LOWER(action) = 'buy'
              AND signal_price IS NOT NULL
              {extra}
            ORDER BY id DESC
            LIMIT ?
        """, params).fetchall()

    return rows


def summarize(results):
    total = len(results)
    if total == 0:
        print("No BUY rows found.")
        return

    actual_approved = [r for r in results if r["actual_approved"]]
    actual_rejected = [r for r in results if not r["actual_approved"]]

    policy_block = [r for r in results if r["policy_decision"] == "block"]
    policy_size_down = [r for r in results if r["policy_decision"] == "size_down"]
    policy_allow = [r for r in results if r["policy_decision"] == "allow"]

    would_block_actual_approved = [r for r in actual_approved if r["policy_decision"] == "block"]
    would_allow_actual_rejected = [r for r in actual_rejected if r["policy_decision"] == "allow"]

    print()
    print("── Summary ───────────────────────────────────────────")
    print(f"BUY rows analyzed              : {total}")
    print(f"Actually approved              : {len(actual_approved)}")
    print(f"Actually rejected              : {len(actual_rejected)}")
    print()
    print(f"Policy allow                   : {len(policy_allow)}")
    print(f"Policy size_down               : {len(policy_size_down)}")
    print(f"Policy block                   : {len(policy_block)}")
    print()
    print(f"Policy would block approved    : {len(would_block_actual_approved)}")
    print(f"Policy would allow rejected    : {len(would_allow_actual_rejected)}")

    by_policy = defaultdict(int)
    by_symbol_block = defaultdict(int)
    by_actual_reject_policy_allow = defaultdict(int)
    by_actual_reject_cat = defaultdict(int)

    for r in results:
        by_policy[r["policy_decision"]] += 1
        if r["policy_decision"] == "block":
            by_symbol_block[r["symbol"]] += 1
        if not r["actual_approved"] and r["policy_decision"] == "allow":
            by_actual_reject_policy_allow[r["actual_rejection_category"]] += 1
        if not r["actual_approved"]:
            by_actual_reject_cat[r["actual_rejection_category"]] += 1

    print()
    print("── Policy block by symbol ────────────────────────────")
    if not by_symbol_block:
        print("  none")
    else:
        for sym, n in sorted(by_symbol_block.items(), key=lambda x: -x[1])[:20]:
            print(f"  {sym:<8} {n}")

    print()
    print("── Rejected categories policy would allow ────────────")
    if not by_actual_reject_policy_allow:
        print("  none")
    else:
        for cat, n in sorted(by_actual_reject_policy_allow.items(), key=lambda x: -x[1]):
            print(f"  {cat:<28} {n}")

    print()
    print("── Actual rejection category counts ──────────────────")
    if not by_actual_reject_cat:
        print("  none")
    else:
        for cat, n in sorted(by_actual_reject_cat.items(), key=lambda x: -x[1]):
            print(f"  {cat:<28} {n}")


def print_samples(results, limit=25):
    print()
    print("── Sample: approved trades policy would block ─────────")
    rows = [
        r for r in results
        if r["actual_approved"] and r["policy_decision"] == "block"
    ]

    if not rows:
        print("  none")
    else:
        for r in rows[:limit]:
            print(
                f"  {r['symbol']:<6} policy={r['policy_decision']:<10} "
                f"opp={r.get('opportunity_score_100')} "
                f"pred={r.get('prediction_decision')} "
                f"setup={r.get('setup_label')}/{r.get('setup_policy_action')} "
                f"reason={r.get('policy_reason')}"
            )

    print()
    print("── Sample: rejected trades policy would allow ─────────")
    rows = [
        r for r in results
        if not r["actual_approved"] and r["policy_decision"] == "allow"
    ]

    if not rows:
        print("  none")
    else:
        for r in rows[:limit]:
            print(
                f"  {r['symbol']:<6} actual_reject={r['actual_rejection_category']:<24} "
                f"opp={r.get('opportunity_score_100')} "
                f"pred={r.get('prediction_decision')} "
                f"setup={r.get('setup_label')}/{r.get('setup_policy_action')} "
                f"supports={','.join(r.get('supports') or [])}"
            )



def build_policy_backtest_summary(results):
    total = len(results)
    actual_approved = [r for r in results if r["actual_approved"]]
    actual_rejected = [r for r in results if not r["actual_approved"]]

    policy_allow = [r for r in results if r["policy_decision"] == "allow"]
    policy_size_down = [r for r in results if r["policy_decision"] == "size_down"]
    policy_block = [r for r in results if r["policy_decision"] == "block"]

    would_block_approved = [r for r in actual_approved if r["policy_decision"] == "block"]
    would_allow_rejected = [r for r in actual_rejected if r["policy_decision"] == "allow"]

    by_symbol = defaultdict(lambda: {"total": 0, "allow": 0, "size_down": 0, "block": 0})
    by_rejection_category = defaultdict(lambda: {"total": 0, "policy_allow": 0, "policy_size_down": 0, "policy_block": 0})

    for r in results:
        sym = r["symbol"] or "UNKNOWN"
        by_symbol[sym]["total"] += 1
        by_symbol[sym][r["policy_decision"]] += 1

        if not r["actual_approved"]:
            cat = r["actual_rejection_category"]
            by_rejection_category[cat]["total"] += 1
            by_rejection_category[cat][f"policy_{r['policy_decision']}"] += 1

    approved_n = len(actual_approved)
    rejected_n = len(actual_rejected)
    block_approved_rate = len(would_block_approved) / max(approved_n, 1)
    allow_rejected_rate = len(would_allow_rejected) / max(rejected_n, 1)

    if total == 0:
        recommendation = "observe"
        reason = "no rows analyzed"
    elif approved_n < 10 and rejected_n >= 25 and allow_rejected_rate > 0.50:
        recommendation = "policy_too_loose"
        reason = (
            f"approved sample too small ({approved_n}), but policy would allow "
            f"{allow_rejected_rate * 100:.1f}% of rejected buys"
        )
    elif approved_n < 10:
        recommendation = "observe"
        reason = f"approved sample too small for strictness judgment: {approved_n} approved buys"
    elif allow_rejected_rate > 0.50:
        recommendation = "policy_too_loose"
        reason = f"policy would allow {allow_rejected_rate * 100:.1f}% of actually rejected buys"
    elif block_approved_rate > 0.30:
        recommendation = "policy_too_strict"
        reason = f"policy would block {block_approved_rate * 100:.1f}% of actually approved buys"
    else:
        recommendation = "reasonable"
        reason = "policy replay is within rough tolerance"

    return {
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        "rows_analyzed": total,
        "actual_approved": len(actual_approved),
        "actual_rejected": len(actual_rejected),
        "policy_allow": len(policy_allow),
        "policy_size_down": len(policy_size_down),
        "policy_block": len(policy_block),
        "policy_would_block_approved": len(would_block_approved),
        "policy_would_allow_rejected": len(would_allow_rejected),
        "recommendation": recommendation,
        "reason": reason,
        "by_symbol": dict(sorted(by_symbol.items())),
        "by_rejection_category": dict(sorted(by_rejection_category.items())),
    }


def write_policy_backtest_summary(results):
    summary = build_policy_backtest_summary(results)
    POLICY_BACKTEST_SUMMARY_FILE.write_text(json.dumps(summary, indent=2, sort_keys=True))
    print(f"Wrote {POLICY_BACKTEST_SUMMARY_FILE}")
    return summary

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="YYYY-MM-DD, default=today")
    parser.add_argument("--week", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--symbol")
    parser.add_argument("--limit", type=int, default=500)
    parser.add_argument("--samples", type=int, default=25)
    parser.add_argument("--write-summary", action="store_true", help="Write policy_backtest_summary.json")
    args = parser.parse_args()

    print("=" * 72)
    print("  Policy Backtest")
    print("=" * 72)

    rows = load_rows(args)
    results = [policy_replay(r) for r in rows]

    summarize(results)
    print_samples(results, limit=args.samples)

    if args.write_summary:
        write_policy_backtest_summary(results)


if __name__ == "__main__":
    main()
