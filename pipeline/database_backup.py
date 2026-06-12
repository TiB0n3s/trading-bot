#!/usr/bin/env python3
"""Back up operational SQLite databases and verify restore readability."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.database_backup_service import (  # noqa: E402
    BACKUP_TIER_RETENTION_DAYS,
    DEFAULT_BACKUP_TIER,
    DEFAULT_DB_NAMES,
    DatabaseBackupService,
)


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", default=str(ROOT))
    parser.add_argument("--backup-dir", default=str(ROOT / "backups" / "databases"))
    parser.add_argument("--retention-days", type=int, default=None)
    parser.add_argument(
        "--backup-tier",
        choices=sorted(BACKUP_TIER_RETENTION_DAYS),
        default=DEFAULT_BACKUP_TIER,
        help="GFS tier label for backup placement and retention pruning.",
    )
    parser.add_argument(
        "--db",
        action="append",
        dest="db_names",
        help="Database filename to back up. Can be repeated. Defaults to trades/predictions/jobs.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json-manifest", action="store_true")
    parser.add_argument(
        "--skip-recent-full-hours",
        type=float,
        default=None,
        help=(
            "Reuse a recent verified full backup instead of copying the DB again. "
            "This writes a fresh manifest with status=reused_recent_full."
        ),
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    service = DatabaseBackupService(
        base_dir=Path(args.base_dir),
        backup_dir=Path(args.backup_dir),
    )
    retention_days = (
        args.retention_days
        if args.retention_days is not None
        else BACKUP_TIER_RETENTION_DAYS[args.backup_tier]
    )
    manifest = service.run(
        db_names=args.db_names or DEFAULT_DB_NAMES,
        retention_days=retention_days,
        dry_run=args.dry_run,
        skip_recent_full_hours=args.skip_recent_full_hours,
        backup_tier=args.backup_tier,
    )
    manifest_path = None if args.dry_run else service.write_manifest(manifest)

    print("database_backup_manifest", manifest_path or "-")
    print(
        f"tier={manifest.backup_tier} backed_up={manifest.backed_up_count} "
        f"reused={manifest.reused_count} missing={manifest.missing_count} failed={manifest.failed_count}"
    )
    for row in manifest.results:
        backup_path = row.backup_path or "-"
        detail = row.error or row.integrity_check or row.status
        print(f"{row.name}: status={row.status} backup={backup_path} detail={detail}")

    return 0 if manifest.ok or args.dry_run else 1


if __name__ == "__main__":
    raise SystemExit(main())
