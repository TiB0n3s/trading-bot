from __future__ import annotations

from pathlib import Path

from repositories.ops_check_repo import OpsCheckRepository

EM_DASH = "\u2014"


def run_peak_bucket_report(target_date: str | None = None, *, base_dir: Path) -> bool:
    repo = OpsCheckRepository(base_dir / "trades.db")
    if not repo.exists():
        print("[WARN] trades.db not found")
        return False

    label = target_date or "all sessions"
    print(f"\n=== Peak Bucket \u2192 Realized P&L Report ({label}) ===\n")

    rows = repo.peak_bucket_rows(target_date)
    if not rows:
        print(f"  No matched trades with MFE data for {label}.")
        print("  Run: python3 trade_matcher.py")
        return True

    print(
        f"  {'peak_bucket':<12} {'trades':>6} {'avg_mfe%':>9} {'avg_pnl%':>9} "
        f"{'win%':>6} {'avg_cap':>8} {'<0':>4} {'wbl':>4} "
        f"{'weak':>5} {'avg_floor':>9} {'floor':>5} {'guard':>5}"
    )
    print(
        f"  {'-'*12} {'-'*6} {'-'*9} {'-'*9} {'-'*6} {'-'*8} {'-'*4} {'-'*4} "
        f"{'-'*5} {'-'*9} {'-'*5} {'-'*5}"
    )
    for r in rows:
        avg_mfe_s = f"{r['avg_mfe']:>9.3f}" if r["avg_mfe"] is not None else f"{EM_DASH:>9}"
        avg_pnl_s = f"{r['avg_pnl']:>9.3f}" if r["avg_pnl"] is not None else f"{EM_DASH:>9}"
        avg_cap_s = f"{r['avg_capture']:>8.3f}" if r["avg_capture"] is not None else f"{EM_DASH:>8}"
        avg_floor_s = (
            f"{r['avg_peak_lock_floor']:>9.3f}"
            if r["avg_peak_lock_floor"] is not None
            else f"{EM_DASH:>9}"
        )
        print(
            f"  {r['peak_bucket']:<12} {r['trades']:>6} {avg_mfe_s} {avg_pnl_s} "
            f"{r['win_rate']:>6.1f} {avg_cap_s} {r['exits_below_zero']:>4} "
            f"{r['winner_became_loser']:>4} {r['weak_entries']:>5} {avg_floor_s} "
            f"{r['floor_triggered']:>5} {r['would_have_been_winner_became_loser']:>5}"
        )

    total = repo.peak_bucket_total(target_date)
    if total:
        print(f"\n  Total matched trades: {total['n']}  |  With MFE data: {total['with_mfe']}")
    print()
    return True


def run_winner_became_loser(target_date: str, *, base_dir: Path) -> bool:
    repo = OpsCheckRepository(base_dir / "trades.db")
    if not repo.exists():
        print("[WARN] trades.db not found")
        return False

    mfe_threshold = 0.40
    print(f"\n=== Winner-Became-Loser Report: {target_date} ===\n")

    summary = repo.winner_became_loser_summary(target_date, mfe_threshold)
    if not summary or summary["total"] == 0:
        print(f"  No matched trades for {target_date}. Run: python3 trade_matcher.py")
        return True

    print(
        f"  Matched trades : {summary['total']}\n"
        f"  With MFE data  : {summary['has_mfe']}\n"
        f"  Winner\u2192loser   : {summary['true_wbl']}  (MFE >= {mfe_threshold}%, realized <= 0)\n"
        f"  Poor capture   : {summary['poor_capture']}  (MFE >= {mfe_threshold}%, capture < 0.50)\n"
    )

    wbl_rows = repo.winner_became_loser_rows(target_date, mfe_threshold)
    if wbl_rows:
        print(f"  Winner-became-loser (MFE >= {mfe_threshold}%, realized <= 0):")
        print(
            f"  {'sym':<6} {'mfe%':>6} {'pnl%':>7} {'ratio':>7} "
            f"{'hold':>7} {'setup':<12} {'weak':>4} {'floor':>6} {'tier':<12} {'hit':>3} exit_reason"
        )
        print(
            f"  {'-'*6} {'-'*6} {'-'*7} {'-'*7} {'-'*7} {'-'*12} "
            f"{'-'*4} {'-'*6} {'-'*12} {'-'*3} {'-'*40}"
        )
        for r in wbl_rows:
            ratio_s = f"{r['capture_ratio']:>7.3f}" if r["capture_ratio"] is not None else f"{EM_DASH:>7}"
            floor_s = (
                f"{r['peak_lock_floor_pct']:>6.2f}"
                if r["peak_lock_floor_pct"] is not None
                else f"{EM_DASH:>6}"
            )
            exit_s = (r["exit_reason"] or "")[:50]
            print(
                f"  {r['symbol']:<6} {r['mfe_pct']:>6.3f} {r['realized_pnl_pct']:>7.3f} "
                f"{ratio_s} {(r['holding_minutes'] or 0):>7.1f} "
                f"{(r['setup_policy_action'] or 'none'):<12} "
                f"{r['weak_entry_context']:>4} {floor_s} "
                f"{(r['peak_lock_tier'] or 'none'):<12} {r['floor_triggered']:>3} {exit_s}"
            )
            if r["exit_snapshot_id"] is not None:
                print(
                    f"      exit_snapshot={r['exit_snapshot_id']} "
                    f"trigger={r['exit_snapshot_trigger'] or '-'} "
                    f"missed_lock={r['would_have_been_winner_became_loser']} "
                    f"avoided_dd={r['avoided_drawdown_pct'] if r['avoided_drawdown_pct'] is not None else EM_DASH} "
                    f"missed_upside={r['missed_upside_pct'] if r['missed_upside_pct'] is not None else EM_DASH} "
                    f"post30={r['post_exit_return_30m_pct'] if r['post_exit_return_30m_pct'] is not None else EM_DASH} "
                    f"post60={r['post_exit_return_60m_pct'] if r['post_exit_return_60m_pct'] is not None else EM_DASH} "
                    f"reentry={r['reentry_window_summary'] or '-'}"
                )
            else:
                print(
                    f"      exit_snapshot=missing missed_lock={r['would_have_been_winner_became_loser']} "
                    f"post_exit_recovery=unknown"
                )
    else:
        print(f"  No winner-became-loser trades for {target_date}.")

    print()
    poor_rows = repo.poor_capture_rows(target_date, mfe_threshold)
    if poor_rows:
        print(f"  Poor capture (MFE >= {mfe_threshold}%, realized > 0, capture < 0.50):")
        print(
            f"  {'sym':<6} {'mfe%':>6} {'pnl%':>7} {'ratio':>7} "
            f"{'hold':>7} {'setup':<12} exit_reason"
        )
        print(f"  {'-'*6} {'-'*6} {'-'*7} {'-'*7} {'-'*7} {'-'*12} {'-'*40}")
        for r in poor_rows:
            ratio_s = f"{r['capture_ratio']:>7.3f}" if r["capture_ratio"] is not None else f"{EM_DASH:>7}"
            exit_s = (r["exit_reason"] or "")[:50]
            print(
                f"  {r['symbol']:<6} {r['mfe_pct']:>6.3f} {r['realized_pnl_pct']:>7.3f} "
                f"{ratio_s} {(r['holding_minutes'] or 0):>7.1f} "
                f"{(r['setup_policy_action'] or 'none'):<12} {exit_s}"
            )
    else:
        print(f"  No poor-capture trades for {target_date}.")

    print()
    all_rows = repo.all_mfe_rows_for_date(target_date)
    if all_rows:
        print("  All trades with MFE (sorted by capture ratio, worst first):")
        print(f"  {'sym':<6} {'mfe%':>6} {'pnl%':>7} {'ratio':>7} {'weak':>4} {'floor':>6}  setup")
        print(f"  {'-'*6} {'-'*6} {'-'*7} {'-'*7} {'-'*4} {'-'*6}  {'-'*14}")
        for r in all_rows:
            ratio_s = f"{r['capture_ratio']:>7.3f}" if r["capture_ratio"] is not None else f"{EM_DASH:>7}"
            floor_s = (
                f"{r['peak_lock_floor_pct']:>6.2f}"
                if r["peak_lock_floor_pct"] is not None
                else f"{EM_DASH:>6}"
            )
            print(
                f"  {r['symbol']:<6} {r['mfe_pct']:>6.3f} {r['realized_pnl_pct']:>7.3f} "
                f"{ratio_s} {r['weak_entry_context']:>4} {floor_s}  "
                f"{r['setup_policy_action'] or 'none'}"
            )

    print()
    return True
