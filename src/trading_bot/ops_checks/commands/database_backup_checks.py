"""Operator report for database backup manifests."""

from __future__ import annotations

import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from ops.database_backup_service import (
    DEFAULT_DB_NAMES,
    RESTORABLE_BACKUP_STATUSES,
    DatabaseRestoreDrillService,
)


def _load_latest_manifest(backup_dir: Path) -> tuple[Path | None, dict[str, Any] | None]:
    manifests = sorted(
        backup_dir.glob("**/database_backup_*.manifest.json"),
        key=lambda p: p.stat().st_mtime,
    )
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


def _elapsed_minutes(value: str) -> float | None:
    text = value.strip()
    if not text:
        return None
    days = 0
    if "-" in text:
        day_text, text = text.split("-", 1)
        try:
            days = int(day_text)
        except ValueError:
            return None
    parts = text.split(":")
    try:
        if len(parts) == 3:
            hours, minutes, seconds = (int(part) for part in parts)
        elif len(parts) == 2:
            hours = 0
            minutes, seconds = (int(part) for part in parts)
        else:
            return None
    except ValueError:
        return None
    return days * 24 * 60 + hours * 60 + minutes + seconds / 60


def _active_backup_processes() -> list[dict[str, Any]]:
    result = subprocess.run(
        ["ps", "-eo", "pid,ppid,stat,etime,args"],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        return []
    rows = []
    for line in result.stdout.splitlines()[1:]:
        parts = line.strip().split(None, 4)
        if len(parts) < 5:
            continue
        pid, ppid, stat, etime, args = parts
        if "py_compile" in args or "pytest" in args:
            continue
        is_backup = (
            " pipeline/database_backup.py" in f" {args}"
            or "--job-name daily_db_backup" in args
            or "--job-name weekly_db_backup" in args
            or "--job-name monthly_db_backup" in args
        )
        if not is_backup:
            continue
        if "grep" in args:
            continue
        rows.append(
            {
                "pid": pid,
                "ppid": ppid,
                "stat": stat,
                "etime": etime,
                "elapsed_minutes": _elapsed_minutes(etime),
                "args": args,
            }
        )
    return rows


def _manifest_referenced_paths(backup_dir: Path) -> set[Path]:
    paths: set[Path] = set()
    for manifest_path in backup_dir.glob("**/database_backup_*.manifest.json"):
        try:
            manifest = json.loads(manifest_path.read_text())
        except Exception:
            continue
        for row in manifest.get("results", []):
            backup_path = row.get("backup_path")
            if backup_path:
                paths.add(Path(str(backup_path)).resolve())
    return paths


def _recent_unmanifested_backup_artifacts(
    backup_dir: Path,
    latest_manifest_path: Path | None,
) -> list[Path]:
    if latest_manifest_path is None or not latest_manifest_path.exists():
        return []
    latest_mtime = latest_manifest_path.stat().st_mtime
    referenced = _manifest_referenced_paths(backup_dir)
    artifacts = []
    for db_name in DEFAULT_DB_NAMES:
        for path in backup_dir.glob(f"**/{db_name}"):
            if "restore_drills" in path.parts or "quarantine" in path.parts:
                continue
            try:
                resolved = path.resolve()
                stat = path.stat()
            except OSError:
                continue
            if resolved in referenced:
                continue
            if stat.st_mtime > latest_mtime:
                artifacts.append(path)
    return sorted(artifacts)


def _missing_manifest_backup_paths(manifest: dict[str, Any] | None) -> list[Path]:
    if not manifest:
        return []
    missing = []
    for row in manifest.get("results", []):
        status = row.get("status")
        backup_path = row.get("backup_path")
        if status not in RESTORABLE_BACKUP_STATUSES:
            continue
        if not backup_path or not Path(str(backup_path)).exists():
            missing.append(Path(str(backup_path or "")))
    return missing


def _load_heartbeat(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return {"status": "unreadable", "path": str(path)}


def _heartbeat_age_minutes(heartbeat: dict[str, Any] | None) -> float | None:
    if not heartbeat:
        return None
    raw = heartbeat.get("updated_at")
    if not raw:
        return None
    try:
        dt = datetime.fromisoformat(str(raw).replace("Z", "+00:00"))
    except Exception:
        return None
    return round((datetime.now(timezone.utc) - dt.astimezone(timezone.utc)).total_seconds() / 60, 2)


def run_database_backup_report(
    *,
    base_dir: Path,
    max_age_hours: float = 30.0,
    stale_process_minutes: float = 45.0,
) -> bool:
    backup_dir = base_dir / "backups" / "databases"
    heartbeat_path = base_dir / "backups" / "database_backup_heartbeat.json"
    manifest_path, manifest = _load_latest_manifest(backup_dir)
    age_hours = _age_hours(manifest_path)
    active_processes = _active_backup_processes()
    stale_processes = [
        row
        for row in active_processes
        if (row.get("elapsed_minutes") or 0) >= stale_process_minutes
        or str(row.get("stat") or "").startswith("D")
    ]
    recent_unmanifested = _recent_unmanifested_backup_artifacts(backup_dir, manifest_path)
    heartbeat = _load_heartbeat(heartbeat_path)
    heartbeat_age = _heartbeat_age_minutes(heartbeat)
    stale_heartbeat = (
        heartbeat is not None
        and heartbeat.get("status") == "running"
        and heartbeat_age is not None
        and heartbeat_age >= stale_process_minutes
    )
    missing_manifest_artifacts = _missing_manifest_backup_paths(manifest)

    print()
    print("=" * 72)
    print("  Database Backup Health")
    print("=" * 72)
    print("report_version          : database_backup_health_v1")
    print("runtime_effect          : diagnostic_only_no_runtime_change")
    print(f"backup_dir              : {backup_dir}")
    print(f"latest_manifest         : {manifest_path or '-'}")
    print(f"latest_age_hours        : {age_hours if age_hours is not None else '-'}")
    print(f"heartbeat_file          : {heartbeat_path}")
    print(f"heartbeat_status        : {(heartbeat or {}).get('status') or '-'}")
    print(f"heartbeat_age_minutes   : {heartbeat_age if heartbeat_age is not None else '-'}")
    heartbeat_progress = (heartbeat or {}).get("progress") or {}
    print(f"heartbeat_phase         : {heartbeat_progress.get('phase') or '-'}")
    print(f"active_backup_processes : {len(active_processes)}")
    print(f"stale_backup_processes  : {len(stale_processes)}")
    print(f"unmanifested_artifacts  : {len(recent_unmanifested)}")
    print(f"missing_manifest_artifacts: {len(missing_manifest_artifacts)}")

    if manifest is None:
        print()
        print("[WARN] no readable database backup manifest found")
        print("next_command            : python3 pipeline/database_backup.py")
        return False

    summary = manifest.get("summary", {})
    stale = age_hours is None or age_hours > max_age_hours
    failed = int(summary.get("failed_count") or 0)
    backed_up = int(summary.get("backed_up_count") or 0)
    reused = int(summary.get("reused_count") or 0)
    missing = int(summary.get("missing_count") or 0)

    print(f"manifest_version        : {manifest.get('report_version')}")
    print(f"created_at              : {manifest.get('created_at')}")
    print(f"dry_run                 : {manifest.get('dry_run')}")
    print(f"backed_up_count         : {backed_up}")
    print(f"reused_count            : {reused}")
    print(f"backup_tier             : {manifest.get('backup_tier') or 'legacy'}")
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
    if active_processes:
        print("Active backup processes")
        for row in active_processes:
            print(
                f"  pid={row.get('pid')} stat={row.get('stat')} "
                f"elapsed={row.get('etime')} args={row.get('args')}"
            )
        print()
    if recent_unmanifested:
        print("Recent backup artifacts without manifest references")
        for path in recent_unmanifested:
            print(f"  {path}")
        print()
    if missing_manifest_artifacts:
        print("Manifest-referenced backup artifacts missing from disk")
        for path in missing_manifest_artifacts:
            print(f"  {path}")
        print()
    if stale_processes:
        print("[FAIL] active database backup process is stale or in D-state I/O wait")
        return False
    if stale_heartbeat:
        print("[FAIL] database backup heartbeat is stale while marked running")
        return False
    if recent_unmanifested:
        print("[FAIL] recent database backup artifact exists without a manifest reference")
        return False
    if missing_manifest_artifacts:
        print("[FAIL] latest database backup manifest references missing backup artifacts")
        return False
    if failed:
        print("[FAIL] latest database backup manifest has failed backup rows")
        return False
    if stale:
        print(f"[WARN] latest database backup manifest is older than {max_age_hours:.1f} hours")
        return False
    if backed_up + reused <= 0:
        print("[WARN] latest database backup did not verify or reuse any database files")
        return False

    print("[OK] latest database backup manifest is fresh and restorable")
    return True


def run_database_restore_drill(
    *,
    base_dir: Path,
    backup_dir: Path | None = None,
) -> bool:
    backup_root = backup_dir or base_dir / "backups" / "databases"
    service = DatabaseRestoreDrillService(backup_dir=backup_root)
    restore_dir = (
        backup_root
        / "restore_drills"
        / f"restore_{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}"
    )
    manifest = service.run(restore_dir=restore_dir)
    manifest_path = service.write_manifest(manifest)

    print()
    print("=" * 72)
    print("  Database Restore Drill")
    print("=" * 72)
    print(f"report_version          : {manifest.report_version}")
    print(f"runtime_effect          : {manifest.runtime_effect}")
    print(f"backup_dir              : {backup_root}")
    print(f"backup_manifest         : {manifest.backup_manifest_path or '-'}")
    print(f"restore_dir             : {manifest.restore_dir}")
    print(f"drill_manifest          : {manifest_path}")
    print(f"verified_count          : {manifest.verified_count}")
    print(f"skipped_count           : {manifest.skipped_count}")
    print(f"failed_count            : {manifest.failed_count}")

    print()
    print("Restored databases")
    for row in manifest.results:
        print(
            f"  {row.name:<15} status={row.status:<8} "
            f"integrity={row.integrity_check or '-':<8} "
            f"tables={row.table_count if row.table_count is not None else '-':<4} "
            f"backup={row.backup_path or '-'}"
        )
        if row.error:
            print(f"    error={row.error}")

    print()
    if manifest.ok:
        print("[OK] latest database backups restored and passed integrity checks")
        return True
    print("[FAIL] database restore drill did not verify any restorable backups")
    return False
