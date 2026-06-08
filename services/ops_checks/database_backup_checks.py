"""Operator report for database backup manifests."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


def _load_latest_manifest(backup_dir: Path) -> tuple[Path | None, dict[str, Any] | None]:
    manifests = sorted(backup_dir.glob("database_backup_*.manifest.json"))
    if not manifests:
        return None, None
    latest = manifests[-1]
    try:
        return latest, json.loads(latest.read_text())
    except Exception:
        return latest, None


def _age_hours(path: Path | None) -> float | None:
    if path is None or not path.exists():
        return None
    return round((datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) / 3600, 2)


def run_database_backup_report(*, base_dir: Path, max_age_hours: float = 30.0) -> bool:
    backup_dir = base_dir / "backups" / "databases"
    manifest_path, manifest = _load_latest_manifest(backup_dir)
    age_hours = _age_hours(manifest_path)

    print()
    print("=" * 72)
    print("  Database Backup Health")
    print("=" * 72)
    print("report_version          : database_backup_health_v1")
    print("runtime_effect          : diagnostic_only_no_runtime_change")
    print(f"backup_dir              : {backup_dir}")
    print(f"latest_manifest         : {manifest_path or '-'}")
    print(f"latest_age_hours        : {age_hours if age_hours is not None else '-'}")

    if manifest is None:
        print()
        print("[WARN] no readable database backup manifest found")
        print("next_command            : python3 pipeline/database_backup.py")
        return False

    summary = manifest.get("summary", {})
    stale = age_hours is None or age_hours > max_age_hours
    failed = int(summary.get("failed_count") or 0)
    backed_up = int(summary.get("backed_up_count") or 0)
    missing = int(summary.get("missing_count") or 0)

    print(f"manifest_version        : {manifest.get('report_version')}")
    print(f"created_at              : {manifest.get('created_at')}")
    print(f"dry_run                 : {manifest.get('dry_run')}")
    print(f"backed_up_count         : {backed_up}")
    print(f"missing_count           : {missing}")
    print(f"failed_count            : {failed}")
    print(f"stale                   : {stale}")

    print()
    print("Databases")
    for row in manifest.get("results", []):
        print(
            f"  {row.get('name'):<15} status={row.get('status'):<8} "
            f"integrity={row.get('integrity_check') or '-':<8} "
            f"tables={row.get('table_count') if row.get('table_count') is not None else '-':<4} "
            f"backup={row.get('backup_path') or '-'}"
        )

    print()
    if failed:
        print("[FAIL] latest database backup manifest has failed backup rows")
        return False
    if stale:
        print(f"[WARN] latest database backup manifest is older than {max_age_hours:.1f} hours")
        return False
    if backed_up <= 0:
        print("[WARN] latest database backup did not verify any database files")
        return False

    print("[OK] latest database backup manifest is fresh and verified")
    return True
