from __future__ import annotations

from collections import Counter
from pathlib import Path

from repositories.ops_check_repo import OpsCheckRepository

EM_DASH = "\u2014"


def run_conviction_stack_report(target_date: str, *, base_dir: Path) -> bool:
    repo = OpsCheckRepository(base_dir / "trades.db")
    if not repo.exists():
        print("[WARN] trades.db not found")
        return False

    print(f"\n=== Conviction Stack Report: {target_date} ===\n")
    rows = repo.conviction_stack_rows(target_date)
    if not rows:
        print(f"  No BUY signals for {target_date}.")
        return True

    total = len(rows)
    approved = sum(1 for r in rows if r["approved"])
    capped = sum(1 for r in rows if r["effective_size_cap_pct"] is not None)
    uncapped = total - capped

    print(f"  BUY signals: {total}  approved: {approved}  capped: {capped}  uncapped: {uncapped}\n")
    print("  Cap Distribution (max_position_size_pct_override before execution):")
    print(f"  {'Cap Level':<20} {'Count':>6} {'Appr':>5} {'Appr%':>6}")
    print(f"  {'-'*20} {'-'*6} {'-'*5} {'-'*6}")

    cap_buckets = [
        ("uncapped (None)", lambda r: r["effective_size_cap_pct"] is None),
        ("1.25%+", lambda r: r["effective_size_cap_pct"] is not None and float(r["effective_size_cap_pct"]) >= 1.25),
        ("0.90\u20131.25%", lambda r: r["effective_size_cap_pct"] is not None and 0.90 <= float(r["effective_size_cap_pct"]) < 1.25),
        ("0.80\u20130.90%", lambda r: r["effective_size_cap_pct"] is not None and 0.80 <= float(r["effective_size_cap_pct"]) < 0.90),
        ("0.75\u20130.80%", lambda r: r["effective_size_cap_pct"] is not None and 0.75 <= float(r["effective_size_cap_pct"]) < 0.80),
        ("0.65\u20130.75%", lambda r: r["effective_size_cap_pct"] is not None and 0.65 <= float(r["effective_size_cap_pct"]) < 0.75),
        ("0.50\u20130.65%", lambda r: r["effective_size_cap_pct"] is not None and 0.50 <= float(r["effective_size_cap_pct"]) < 0.65),
        ("below 0.50%", lambda r: r["effective_size_cap_pct"] is not None and float(r["effective_size_cap_pct"]) < 0.50),
    ]

    for label, pred in cap_buckets:
        bucket_rows = [r for r in rows if pred(r)]
        if not bucket_rows:
            continue
        n = len(bucket_rows)
        appr = sum(1 for r in bucket_rows if r["approved"])
        pct = f"{appr/n*100:.0f}%" if n else EM_DASH
        print(f"  {label:<20} {n:>6} {appr:>5} {pct:>6}")

    print("\n  Dominant Limiter Breakdown (which source set the tightest pre-execution cap):")
    print(f"  {'Limiter':<28} {'Count':>6} {'Appr':>5} {'Appr%':>6}")
    print(f"  {'-'*28} {'-'*6} {'-'*5} {'-'*6}")

    limiter_counts: Counter = Counter()
    limiter_approved: Counter = Counter()
    for r in rows:
        lim = r["dominant_limiter"] or "unknown"
        limiter_counts[lim] += 1
        if r["approved"]:
            limiter_approved[lim] += 1

    for lim, n in limiter_counts.most_common():
        appr = limiter_approved[lim]
        pct = f"{appr/n*100:.0f}%" if n else EM_DASH
        flag = " \u2190 dominant" if capped > 0 and n / max(capped, 1) > 0.40 and lim != "uncapped" else ""
        print(f"  {lim:<28} {n:>6} {appr:>5} {pct:>6}{flag}")

    capped_rows = [r for r in rows if r["effective_size_cap_pct"] is not None]
    if capped_rows:
        print(f"\n  Cap Stacking: top combos among {len(capped_rows)} capped signals")
        print(f"  {'dominant_limiter':<26} {'buy_opp':<20} {'setup_action':<12} {'N':>4} {'Appr':>5}")
        print(f"  {'-'*26} {'-'*20} {'-'*12} {'-'*4} {'-'*5}")

        combo_counts: Counter = Counter()
        combo_approved: Counter = Counter()
        for r in capped_rows:
            key = (
                (r["dominant_limiter"] or "unknown")[:25],
                (r["buy_opportunity_recommendation"] or EM_DASH)[:19],
                (r["setup_policy_action"] or EM_DASH)[:11],
            )
            combo_counts[key] += 1
            if r["approved"]:
                combo_approved[key] += 1

        for combo, n in combo_counts.most_common(5):
            appr = combo_approved[combo]
            print(f"  {combo[0]:<26} {combo[1]:<20} {combo[2]:<12} {n:>4} {appr:>5}")

    print()
    return True


def run_buy_opportunity_report(target_date: str, *, base_dir: Path) -> bool:
    repo = OpsCheckRepository(base_dir / "trades.db")
    if not repo.exists():
        print("[WARN] trades.db not found")
        return False

    print(f"\n=== Buy-Opportunity Sizing Report: {target_date} ===\n")
    rows = repo.buy_opportunity_signal_rows(target_date)
    if not rows:
        print(f"  No scored BUY signals for {target_date}.")
        return True

    print("  Signal Counts by Buy-Opportunity Bucket:")
    print(f"  {'Bucket':<22} {'Signals':>8} {'Appr':>5} {'Appr%':>6} {'AvgScore':>9}")
    print(f"  {'-'*22} {'-'*8} {'-'*5} {'-'*6} {'-'*9}")
    for r in rows:
        pct = f"{r['appr_pct']:.0f}%" if r["appr_pct"] is not None else EM_DASH
        avg_s = f"{r['avg_score']:.1f}" if r["avg_score"] is not None else EM_DASH
        print(f"  {(r['rec'] or EM_DASH):<22} {r['signals']:>8} {(r['approved'] or 0):>5} {pct:>6} {avg_s:>9}")

    pnl_rows = repo.buy_opportunity_pnl_rows(target_date)
    if pnl_rows:
        print("\n  Realized P&L by Bucket (from matched_trades):")
        print(f"  {'Bucket':<22} {'Exits':>6} {'AvgPnL':>8} {'WinRate':>8} {'AvgCap':>8}")
        print(f"  {'-'*22} {'-'*6} {'-'*8} {'-'*8} {'-'*8}")
        for r in pnl_rows:
            avg_pnl_s = f"{r['avg_pnl']:+.3f}%" if r["avg_pnl"] is not None else EM_DASH
            win_rate_s = f"{r['wins']/r['exits']*100:.0f}%" if r["exits"] else EM_DASH
            cap_s = f"{r['avg_capture']:.3f}" if r["avg_capture"] is not None else EM_DASH
            print(f"  {(r['rec'] or EM_DASH):<22} {r['exits']:>6} {avg_pnl_s:>8} {win_rate_s:>8} {cap_s:>8}")
    else:
        print(f"\n  No matched exit data yet for {target_date}.")

    cap_rows = repo.buy_opportunity_cap_rows(target_date)
    if cap_rows:
        print("\n  Cap Dominance (buy_opportunity bucket vs actual dominant limiter):")
        print(f"  {'Bucket':<22} {'Dominant Limiter':<28} {'Count':>6}")
        print(f"  {'-'*22} {'-'*28} {'-'*6}")
        for r in cap_rows:
            print(f"  {(r['rec'] or EM_DASH):<22} {(r['dominant_limiter'] or 'uncapped'):<28} {r['n']:>6}")

    dc_rows = repo.buy_opportunity_double_count_row(target_date)
    if dc_rows and dc_rows["n"]:
        print(f"\n  \u26a0 Double-penalized signals (setup block/error AND buy_opp avoid): {dc_rows['n']}")
        print("    These trades are penalized by both setup_policy and buy_opportunity.")
        print("    No action required \u2014 both signals are independently valid \u2014 but note the overlap.")

    print()
    return True


def run_claude_context_audit(target_date: str, *, base_dir: Path) -> bool:
    repo = OpsCheckRepository(base_dir / "trades.db")
    if not repo.exists():
        print("[WARN] trades.db not found")
        return False

    baseline_date = "2026-05-29"
    print(f"\n=== Claude Context Audit: {target_date} ===\n")
    print(f"  Baseline: {baseline_date} (pre-market_context_summary). Target: {target_date}\n")

    daily_rows = repo.claude_daily_approval_rows(target_date)
    if daily_rows:
        print("  Daily BUY Approval Rate (last 14 days):")
        print(f"  {'Date':<12} {'Total':>6} {'Appr':>5} {'Rate':>6}  Note")
        print(f"  {'-'*12} {'-'*6} {'-'*5} {'-'*6}  {'-'*20}")
        for r in daily_rows:
            pct = f"{r['appr_pct']:.0f}%" if r["appr_pct"] is not None else EM_DASH
            note = ""
            if r["day"] == baseline_date:
                note = "\u2190 pre-context-summary"
            elif r["day"] > baseline_date:
                note = "post-context-summary"
            print(f"  {r['day']:<12} {r['total']:>6} {(r['approved'] or 0):>5} {pct:>6}  {note}")

    rej_rows = repo.claude_rejection_reason_rows(target_date)
    if rej_rows:
        print(f"\n  Top Rejection Reasons for {target_date}:")
        print(f"  {'Reason (prefix)':<40} {'Count':>6}")
        print(f"  {'-'*40} {'-'*6}")
        for r in rej_rows:
            reason = (r["rejection_reason"] or "")[:39]
            print(f"  {reason:<40} {r['n']:>6}")

    conf_rows = repo.claude_confidence_rows(target_date)
    if conf_rows:
        print("\n  Claude Confidence Distribution (approved BUYs, last 30 days):")
        print(f"  {'Confidence':<14} {'Count':>6} {'Pct':>6}")
        print(f"  {'-'*14} {'-'*6} {'-'*6}")
        for r in conf_rows:
            print(f"  {(r['confidence'] or EM_DASH):<14} {r['n']:>6} {r['pct']:>5.1f}%")

    print(
        "\n  NOTE: Meaningful before/after comparison requires 5+ post-change sessions."
        "\n  Check again after 2026-06-06 for statistically meaningful patterns."
    )
    print()
    return True
