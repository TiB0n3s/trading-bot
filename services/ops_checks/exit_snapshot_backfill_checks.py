"""Ops check for repairing missing canonical exit snapshots."""

from __future__ import annotations

from services.exit_snapshot_backfill_service import ExitSnapshotBackfillService


def run_exit_snapshot_backfill(
    date: str,
    *,
    end_date: str | None = None,
    dry_run: bool = False,
    limit: int | None = None,
) -> bool:
    result = ExitSnapshotBackfillService().backfill_approved_matched_exits(
        start_date=date,
        end_date=end_date,
        dry_run=dry_run,
        limit=limit,
    )

    print()
    print("=" * 72)
    print("  Exit Snapshot Backfill")
    print("=" * 72)
    print(f"date_range : {result.start_date} -> {result.end_date}")
    print(f"dry_run    : {result.dry_run}")
    print(f"scanned    : {result.scanned}")
    print(f"inserted   : {result.inserted}")

    if result.samples:
        print()
        print("Sample repaired rows:")
        for row in result.samples:
            print(
                "  "
                f"decision={row['decision_snapshot_id']} "
                f"matched={row['matched_trade_id']} "
                f"symbol={row['symbol']} "
                f"exit={row['exit_timestamp']} "
                f"hash={row['canonical_exit_hash'][:12]}"
            )
    elif dry_run:
        print("[OK] no missing approved matched exit snapshots found")

    return True
