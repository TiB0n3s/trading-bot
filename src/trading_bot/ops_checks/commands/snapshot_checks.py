from __future__ import annotations

from pathlib import Path

from repositories.decision_snapshot_repo import DecisionSnapshotRepository


def run_decision_snapshot_health(target_date: str, *, base_dir: Path) -> bool:
    db_path = base_dir / "trades.db"
    repo = DecisionSnapshotRepository(db_path)

    print()
    print("=" * 72)
    print(f"  Decision Snapshots - {target_date}")
    print("=" * 72)

    if not db_path.exists():
        print(f"[FAIL] missing {db_path}")
        return False

    if not repo.table_exists("decision_snapshots"):
        print("[FAIL] decision_snapshots table is missing")
        return False

    ok = True
    summary = repo.summarize_snapshots(target_date)
    print(f"  snapshots              {summary['total']:>8}")
    print(f"  symbols                {summary['symbols']:>8}")
    print(f"  missing_context_hash   {summary['missing_context_hash']:>8}")
    print(f"  missing_git_sha        {summary['missing_git_sha']:>8}")

    print()
    print("Decision distribution")
    if summary["by_decision"]:
        for row in summary["by_decision"]:
            print(f"  {row['final_decision'] or '-':<24} approved={row['approved']} n={row['n']}")
    else:
        print("  none")

    if repo.table_exists("trades"):
        trade_count = repo.trade_count_for_date(target_date)
        snapshot_trade_count = repo.snapshot_trade_count_for_date(target_date)
        print()
        print("Trade coverage")
        print(f"  trades_today           {int(trade_count or 0):>8}")
        print(f"  snapshots_with_trade   {int(snapshot_trade_count or 0):>8}")
        if trade_count and snapshot_trade_count < trade_count:
            print("[WARN] older trades may predate decision snapshot logging")

    if summary["total"] and summary["missing_context_hash"]:
        ok = False
        print("[WARN] some snapshots are missing market_context_hash")

    print()
    print(
        "[OK] decision snapshot check completed"
        if ok
        else "[WARN] decision snapshot check found issues"
    )
    return ok
