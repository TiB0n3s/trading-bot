#!/usr/bin/env python3
"""Back up operational SQLite databases and verify restore readability."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from ops.database_backup_service import DEFAULT_DB_NAMES, DatabaseBackupService  # noqa: E402


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base-dir", default=str(ROOT))
    parser.add_argument("--backup-dir", default=str(ROOT / "backups" / "databases"))
    parser.add_argument("--retention-days", type=int, default=30)
    parser.add_argument(
        "--db",
        action="append",
        dest="db_names",
        help="Database filename to back up. Can be repeated. Defaults to trades/predictions/jobs.",
    )
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json-manifest", action="store_true")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    service = DatabaseBackupService(
        base_dir=Path(args.base_dir),
        backup_dir=Path(args.backup_dir),
    )
    manifest = service.run(
        db_names=args.db_names or DEFAULT_DB_NAMES,
        retention_days=args.retention_days,
        dry_run=args.dry_run,
    )
    manifest_path = service.write_manifest(manifest)

    print("database_backup_manifest", manifest_path)
    print(
        f"backed_up={manifest.backed_up_count} missing={manifest.missing_count} failed={manifest.failed_count}"
    )
    for row in manifest.results:
        backup_path = row.backup_path or "-"
        detail = row.error or row.integrity_check or row.status
        print(f"{row.name}: status={row.status} backup={backup_path} detail={detail}")

    return 0 if manifest.ok or args.dry_run else 1


if __name__ == "__main__":
    raise SystemExit(main())
