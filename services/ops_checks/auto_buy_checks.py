from __future__ import annotations

from pathlib import Path

from repositories import auto_buy_repo


def _int_row_value(row, key: str) -> int:
    if row is None:
        return 0
    return int(row[key] or 0)


def run_auto_buy_health(target_date: str, *, base_dir: Path) -> bool:
    db_path = base_dir / "trades.db"

    print()
    print("=" * 72)
    print(f"  Auto-Buy Candidates - {target_date}")
    print("=" * 72)

    if not db_path.exists():
        print(f"[FAIL] missing {db_path}")
        return False

    if not auto_buy_repo.table_exists("auto_buy_candidates", db_path=db_path):
        print("[WARN] auto_buy_candidates table is missing; run auto_buy_manager.py first")
        return False

    print("Decision distribution")
    rows = auto_buy_repo.candidate_decision_rows(target_date, db_path=db_path)
    if rows:
        for row in rows:
            avg_score = row["avg_score"]
            max_score = row["max_score"]
            avg_s = f"{avg_score:.2f}" if avg_score is not None else "-"
            max_s = f"{max_score:.2f}" if max_score is not None else "-"
            print(f"  {row['decision']:<24} {row['n']:>6} avg={avg_s:>7} max={max_s:>7}")
    else:
        print("  none")

    print()
    cols = auto_buy_repo.table_columns("auto_buy_candidates", db_path=db_path)
    if "hard_block_reason" in cols:
        print("Hard-block reasons")
        rows = auto_buy_repo.candidate_hard_block_reason_rows(target_date, db_path=db_path)
        if rows:
            for row in rows:
                print(f"  {row['hard_block_reason']:<55} {row['n']:>6}")
        else:
            print("  none")
        print()

    print("Top candidates")
    rows = auto_buy_repo.top_candidate_rows(target_date, db_path=db_path)
    if rows:
        for row in rows:
            print(
                f"  {row['timestamp']} {row['symbol']:<6} "
                f"{row['decision']:<22} score={row['score']:<5} "
                f"source={row['signal_source'] or '-':<18} "
                f"session={row['session_trend_label']}/{row['session_trend_score']} "
                f"setup={row['setup_label'] or '-'} "
                f"order={row['order_id'] or '-'}"
            )
    else:
        print("  none")

    print()
    print("Auto-buy audit snapshots")
    if auto_buy_repo.table_exists("auto_buy_decision_snapshots", db_path=db_path):
        row = auto_buy_repo.decision_snapshot_summary(target_date, db_path=db_path)
        print(f"  snapshots             {_int_row_value(row, 'n'):>8}")
        print(f"  submitted             {_int_row_value(row, 'submitted'):>8}")
        print(f"  live_blocked          {_int_row_value(row, 'blocked'):>8}")
    else:
        print("  [WARN] auto_buy_decision_snapshots table missing")

    print()
    print("[OK] auto-buy candidate check completed")
    return True
