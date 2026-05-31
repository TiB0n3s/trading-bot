from __future__ import annotations

from pathlib import Path

from repositories.ops_check_repo import OpsCheckRepository

EM_DASH = "\u2014"


def run_setup_breakdown(target_date: str, *, base_dir: Path) -> bool:
    repo = OpsCheckRepository(base_dir / "trades.db")
    if not repo.exists():
        print("[WARN] trades.db not found")
        return False

    print(f"\n=== Setup Classification Breakdown: {target_date} ===\n")

    rows = repo.setup_overview_rows(target_date)
    if not rows:
        print(f"  No BUY signals found for {target_date}.")
    else:
        print(f"  {'setup_policy_action':<28} {'signals':>7} {'approved':>8} {'rejected':>8}")
        print(f"  {'-'*28} {'-'*7} {'-'*8} {'-'*8}")
        for r in rows:
            print(
                f"  {r['action']:<28} {r['signals']:>7} "
                f"{r['approved']:>8} {r['rejected']:>8}"
            )

    print()
    err_rows = repo.setup_error_symbol_rows(target_date)
    if err_rows:
        print("  Error/unknown by symbol (top 20):")
        print(f"  {'symbol':<8} {'signals':>7} {'approved':>8}  reason")
        print(f"  {'-'*8} {'-'*7} {'-'*8}  {'-'*40}")
        for r in err_rows:
            reason = (r["reason"] or "")[:60]
            print(f"  {r['symbol']:<8} {r['signals']:>7} {r['approved']:>8}  {reason}")
    else:
        print("  No error/unknown signals for this date.")

    print()
    hour_rows = repo.setup_error_hour_rows(target_date)
    if hour_rows:
        print("  Error/unknown by hour (ET):")
        print(f"  {'hour':>5} {'signals':>7} {'approved':>8}")
        print(f"  {'-'*5} {'-'*7} {'-'*8}")
        for r in hour_rows:
            print(f"  {r['hour_et']:>5} {r['signals']:>7} {r['approved']:>8}")

    print()
    feed_rows = repo.setup_feed_error_rows(target_date)
    if feed_rows:
        print("  Feed/setup error breakdown:")
        print(f"  {'error_category':<30} {'signals':>7} {'approved':>8}")
        print(f"  {'-'*30} {'-'*7} {'-'*8}")
        for r in feed_rows:
            print(f"  {r['error_category']:<30} {r['signals']:>7} {r['approved']:>8}")

    print()
    pnl_rows = repo.setup_pnl_rows(target_date)
    if pnl_rows:
        print("  Matched-trade P&L by setup_policy_action:")
        print(
            f"  {'action':<28} {'trades':>6} {'wins':>5} "
            f"{'avg_pnl%':>9} {'total_pnl%':>10}"
        )
        print(f"  {'-'*28} {'-'*6} {'-'*5} {'-'*9} {'-'*10}")
        for r in pnl_rows:
            print(
                f"  {r['spa']:<28} {r['trades']:>6} {r['wins']:>5} "
                f"{r['avg_pnl_pct']:>9} {r['total_pnl_pct']:>10}"
            )
    else:
        print("  No matched trades for this date.")

    print()
    approved_unknown = repo.approved_unknown_setup_rows(target_date)
    if approved_unknown:
        print("  Approved buys with unknown/error setup (P&L detail):")
        print(
            f"  {'symbol':<8} {'action':<8} {'pnl%':>7} {'won':>4} "
            f"{'hold_min':>9}  reason"
        )
        print(f"  {'-'*8} {'-'*8} {'-'*7} {'-'*4} {'-'*9}  {'-'*35}")
        for r in approved_unknown:
            reason = (r["unknown_reason"] or "")[:50]
            print(
                f"  {r['symbol']:<8} {r['setup_policy_action']:<8} "
                f"{r['pnl_pct']:>7} {r['won']:>4} "
                f"{(r['holding_minutes'] or 0):>9.0f}  {reason}"
            )
    else:
        print("  No matched trades with unknown/error setup for this date.")

    print()
    print("  Prediction bucket breakdown (BUY signals):")
    bucket_signal_rows = repo.prediction_bucket_signal_rows(target_date)
    bucket_pnl_rows = repo.prediction_bucket_pnl_rows(target_date)
    pnl_by_bucket = {r["bucket"]: r for r in bucket_pnl_rows}

    if bucket_signal_rows:
        print(
            f"  {'bucket':<16} {'signals':>7} {'appr':>5} {'appr%':>6} "
            f"{'trades':>6} {'wins':>5} {'avg_pnl%':>9} {'note'}"
        )
        print(
            f"  {'-'*16} {'-'*7} {'-'*5} {'-'*6} "
            f"{'-'*6} {'-'*5} {'-'*9} {'-'*20}"
        )
        for r in bucket_signal_rows:
            bucket = r["bucket"]
            pnl = pnl_by_bucket.get(bucket)
            trades = pnl["trades"] if pnl else 0
            wins = pnl["wins"] if pnl else 0
            avg_pnl = pnl["avg_pnl_pct"] if pnl else None
            avg_str = f"{avg_pnl:>9.3f}" if avg_pnl is not None else f"{EM_DASH:>9}"
            note = (
                "ACTIVE gate" if bucket == "weak_below_45" else
                "observe only" if bucket in ("low_45_50", "mid_50_55") else
                "tie-breaker" if bucket == "high_55_plus" else ""
            )
            print(
                f"  {bucket:<16} {r['signals']:>7} {r['approved']:>5} "
                f"{r['approval_rate_pct']:>6} "
                f"{trades:>6} {wins:>5} {avg_str} {note}"
            )
    else:
        print(f"  No BUY signals with ml_prediction_bucket data for {target_date}.")
        print("  (Column added 2026-05-29; prior records will show 'unknown'.)")

    print()
    print("  Capture ratio by exit type:")
    capture_rows = repo.capture_by_exit_type_rows(target_date)
    if capture_rows:
        print(
            f"  {'exit_type':<22} {'n':>4} {'mfe_n':>5} "
            f"{'avg_mfe%':>9} {'avg_pnl%':>9} {'avg_cap':>8} {'wbl':>4}"
        )
        print(f"  {'-'*22} {'-'*4} {'-'*5} {'-'*9} {'-'*9} {'-'*8} {'-'*4}")
        for r in capture_rows:
            avg_mfe_s = f"{r['avg_mfe']:>9.3f}" if r["avg_mfe"] is not None else f"{EM_DASH:>9}"
            avg_pnl_s = f"{r['avg_pnl']:>9.3f}" if r["avg_pnl"] is not None else f"{EM_DASH:>9}"
            avg_cap_s = f"{r['avg_capture']:>8.3f}" if r["avg_capture"] is not None else f"{EM_DASH:>8}"
            print(
                f"  {r['exit_type']:<22} {r['n']:>4} {r['has_mfe']:>5} "
                f"{avg_mfe_s} {avg_pnl_s} {avg_cap_s} {r['winners_became_losers']:>4}"
            )
    else:
        print(f"  No matched trades for {target_date}.")

    print()
    return True
