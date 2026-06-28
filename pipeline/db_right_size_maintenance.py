#!/usr/bin/env python3
"""Automated right-sizing maintenance for the live SQLite workload.

This orchestrates the pieces added for DB workload cleanup:

1. bounded workload report;
2. cold learning archive dry-run or execution;
3. optional compact-copy build and downtime-safe swap;
4. bounded WAL checkpoint;
5. manifest output for audit/replay.

The default is diagnostic-only. Mutating modes are blocked during regular
market hours and when runtime services are active unless explicitly forced.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
for path in (ROOT, ROOT / "scripts", ROOT / "src"):
    text = str(path)
    if text not in sys.path:
        sys.path.insert(0, text)

from market_time import is_market_hours, market_session  # noqa: E402

import pipeline.sqlite_vacuum_swap as sqlite_vacuum_swap  # noqa: E402
from ml_platform.config import DEFAULT_DB_PATH  # noqa: E402
from pipeline.cold_learning_archive import ARCHIVE_ROOT, run_archive  # noqa: E402
from scripts.db_workload_report import build_report  # noqa: E402
from scripts.sqlite_checkpoint import run_checkpoint  # noqa: E402

MANIFEST_VERSION = "db_right_size_maintenance_v1"


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _active_services(service_names: tuple[str, ...]) -> list[dict[str, Any]]:
    return [
        row
        for row in (sqlite_vacuum_swap._service_status(name) for name in service_names)
        if row.get("active")
    ]


def _write_manifest(manifest: dict[str, Any], manifest_dir: Path) -> Path:
    manifest_dir.mkdir(parents=True, exist_ok=True)
    path = manifest_dir / f"db_right_size_maintenance_{_stamp()}.manifest.json"
    manifest["manifest_path"] = str(path)
    path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return path


def _blocked_archive_rows(archive_manifest: dict[str, Any]) -> list[dict[str, Any]]:
    return [
        row
        for row in archive_manifest.get("tables", [])
        if str(row.get("status") or "").startswith("blocked_")
    ]


def _recent_backup_ok(base_dir: Path, *, max_age_hours: float) -> tuple[bool, dict[str, Any]]:
    """Return (ok, info) for the most recent database backup manifest.

    Destructive right-sizing (archive delete / compact swap) must not run unless a
    recent, failure-free backup exists, so a bad archive/swap discovered later can
    be restored. Mirrors the freshness logic in the database-backup health report.
    """
    backup_dir = base_dir / "backups" / "databases"
    manifests = sorted(
        backup_dir.glob("**/database_backup_*.manifest.json"),
        key=lambda p: p.stat().st_mtime,
    )
    if not manifests:
        return False, {"reason": "no_backup_manifest", "backup_dir": str(backup_dir)}
    latest = manifests[-1]
    age_hours = round(
        (datetime.now(timezone.utc).timestamp() - latest.stat().st_mtime) / 3600, 2
    )
    try:
        manifest = json.loads(latest.read_text())
    except Exception:
        return False, {"reason": "unreadable_backup_manifest", "path": str(latest)}
    summary = manifest.get("summary", {}) or {}
    failed = int(summary.get("failed_count") or 0)
    fresh = age_hours <= max_age_hours
    ok = fresh and failed == 0
    return ok, {
        "path": str(latest),
        "age_hours": age_hours,
        "max_age_hours": max_age_hours,
        "failed_count": failed,
        "fresh": fresh,
    }


def run(
    *,
    db_path: Path,
    target_date: date,
    execute_archive: bool,
    build_compact: bool,
    swap_compact: bool,
    checkpoint: bool,
    prune_rollbacks: bool,
    compact_path: Path | None,
    archive_root: Path,
    manifest_dir: Path,
    chunk_size: int,
    max_chunks: int,
    rollback_retention_days: int,
    rollback_min_keep: int,
    skip_training_evidence: bool,
    force: bool,
    skip_market_hours_check: bool,
    skip_service_check: bool,
    service_names: tuple[str, ...],
    dbstat_limit: int,
    dbstat_timeout_sec: float,
    skip_backup_check: bool = False,
    require_backup_max_age_hours: float = 30.0,
) -> dict[str, Any]:
    session = market_session()
    regular_session = is_market_hours()
    mutating = execute_archive or build_compact or swap_compact or checkpoint or prune_rollbacks
    active_services = _active_services(service_names)
    compact_path = compact_path or (
        sqlite_vacuum_swap.DEFAULT_COMPACT_DIR / f"{db_path.name}.compact"
    )

    manifest: dict[str, Any] = {
        "version": MANIFEST_VERSION,
        "started_at": _now_iso(),
        "db_path": str(db_path),
        "target_date": target_date.isoformat(),
        "execute_archive": execute_archive,
        "build_compact": build_compact,
        "swap_compact": swap_compact,
        "checkpoint": checkpoint,
        "prune_rollbacks": prune_rollbacks,
        "rollback_retention_days": rollback_retention_days,
        "rollback_min_keep": rollback_min_keep,
        "compact_path": str(compact_path),
        "archive_root": str(archive_root),
        "market_session": session,
        "is_market_hours": regular_session,
        "skip_market_hours_check": skip_market_hours_check,
        "skip_service_check": skip_service_check,
        "force": force,
        "service_status": [sqlite_vacuum_swap._service_status(name) for name in service_names],
        "actions": [],
    }

    if mutating and regular_session and not skip_market_hours_check and not force:
        manifest["status"] = "blocked_market_hours"
        manifest["reason"] = "right-sizing mutations are off-hours only"
        manifest["finished_at"] = _now_iso()
        _write_manifest(manifest, manifest_dir)
        return manifest

    if swap_compact and active_services and not skip_service_check and not force:
        manifest["status"] = "blocked_active_services"
        manifest["blocked_services"] = active_services
        manifest["finished_at"] = _now_iso()
        _write_manifest(manifest, manifest_dir)
        return manifest

    # Destructive ops (archive delete / compact swap) require a recent, failure-free
    # backup so a bad result can be restored. Fail closed unless explicitly skipped
    # or forced.
    if (execute_archive or swap_compact) and not skip_backup_check and not force:
        # backups/ is co-located with the DB (both at repo root in production), so
        # derive the base from db_path.parent rather than the module ROOT.
        backup_ok, backup_info = _recent_backup_ok(
            db_path.parent, max_age_hours=require_backup_max_age_hours
        )
        manifest["backup_precondition"] = backup_info
        if not backup_ok:
            manifest["status"] = "blocked_no_recent_backup"
            manifest["reason"] = (
                "destructive right-sizing requires a recent verified backup; run "
                "pipeline/database_backup.py first, or pass --skip-backup-check/--force"
            )
            manifest["finished_at"] = _now_iso()
            _write_manifest(manifest, manifest_dir)
            return manifest

    before = build_report(
        db_path,
        dbstat_limit=dbstat_limit,
        dbstat_timeout_sec=dbstat_timeout_sec,
    )
    manifest["source_report_before"] = before
    manifest["actions"].append({"action": "workload_report_before", "status": "complete"})

    archive_manifest = run_archive(
        db_path=db_path,
        archive_root=archive_root,
        target_date=target_date,
        execute=execute_archive,
        chunk_size=chunk_size,
        max_chunks=max_chunks,
        skip_training_evidence=skip_training_evidence,
        selected_tables=None,
    )
    manifest["actions"].append(
        {
            "action": "cold_learning_archive",
            "status": "executed" if execute_archive else "dry_run",
            "manifest_path": archive_manifest.get("manifest_path"),
            "tables": archive_manifest.get("tables", []),
            "training_evidence": archive_manifest.get("training_evidence"),
        }
    )

    blocked = _blocked_archive_rows(archive_manifest)
    if blocked and execute_archive:
        manifest["blocked_tables"] = blocked

    if build_compact or swap_compact:
        vacuum_manifest = sqlite_vacuum_swap.run(
            db_path=db_path,
            compact_path=compact_path,
            manifest_dir=manifest_dir,
            build=build_compact,
            swap=swap_compact,
            replace_build=True,
            force=force,
            skip_service_check=skip_service_check,
            service_names=service_names,
        )
        manifest["actions"].append(
            {
                "action": "sqlite_vacuum_swap",
                "status": vacuum_manifest.get("status"),
                "manifest_path": vacuum_manifest.get("manifest_path"),
                "build_requested": build_compact,
                "swap_requested": swap_compact,
                "source_stats_before": vacuum_manifest.get("source_stats_before"),
                "source_stats_after": vacuum_manifest.get("source_stats_after"),
            }
        )
        if vacuum_manifest.get("status") != "complete" and not force:
            manifest["status"] = "blocked_vacuum_swap"
            manifest["vacuum_swap_status"] = vacuum_manifest.get("status")
            manifest["source_report_after"] = build_report(
                db_path,
                dbstat_limit=0,
                dbstat_timeout_sec=dbstat_timeout_sec,
            )
            manifest["finished_at"] = _now_iso()
            _write_manifest(manifest, manifest_dir)
            return manifest

    if checkpoint:
        checkpoint_result = run_checkpoint(
            db_path,
            mode="TRUNCATE",
            busy_timeout_ms=5000,
            wal_autocheckpoint=1000,
            journal_size_limit=67108864,
            set_wal=True,
        )
        manifest["actions"].append(
            {
                "action": "sqlite_wal_checkpoint",
                "status": "complete",
                "result": checkpoint_result,
            }
        )

    if prune_rollbacks:
        prune_result = sqlite_vacuum_swap.prune_rollback_files(
            db_path=db_path,
            retention_days=rollback_retention_days,
            min_keep=rollback_min_keep,
            dry_run=False,
        )
        manifest["actions"].append(
            {
                "action": "sqlite_rollback_prune",
                "status": "complete",
                "result": prune_result,
            }
        )

    after = build_report(
        db_path,
        dbstat_limit=dbstat_limit,
        dbstat_timeout_sec=dbstat_timeout_sec,
    )
    manifest["source_report_after"] = after
    manifest["status"] = "complete_with_warnings" if blocked and execute_archive else "complete"
    manifest["finished_at"] = _now_iso()
    _write_manifest(manifest, manifest_dir)
    return manifest


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--target-date", default=date.today().isoformat())
    parser.add_argument("--archive-root", default=str(ARCHIVE_ROOT))
    parser.add_argument("--manifest-dir", default=str(sqlite_vacuum_swap.DEFAULT_MANIFEST_DIR))
    parser.add_argument("--chunk-size", type=int, default=5000)
    parser.add_argument("--max-chunks", type=int, default=0, help="0 means no chunk cap")
    parser.add_argument("--execute-archive", action="store_true")
    parser.add_argument(
        "--compact", action="store_true", help="Build compact copy with VACUUM INTO"
    )
    parser.add_argument("--swap", action="store_true", help="Swap compact copy into live db path")
    parser.add_argument("--compact-path")
    parser.add_argument("--checkpoint", action="store_true")
    parser.add_argument("--prune-rollbacks", action="store_true")
    parser.add_argument("--rollback-retention-days", type=int, default=2)
    parser.add_argument(
        "--rollback-min-keep",
        type=int,
        default=1,
        help="Always keep at least this many rollback copies (floored at 1 for safety).",
    )
    parser.add_argument(
        "--skip-backup-check",
        action="store_true",
        help="Skip the recent-backup precondition for destructive archive/swap (unsafe).",
    )
    parser.add_argument("--require-backup-max-age-hours", type=float, default=30.0)
    parser.add_argument("--skip-training-evidence", action="store_true")
    parser.add_argument("--skip-market-hours-check", action="store_true")
    parser.add_argument("--skip-service-check", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--dbstat-limit", type=int, default=0)
    parser.add_argument("--dbstat-timeout-sec", type=float, default=5.0)
    parser.add_argument(
        "--service",
        action="append",
        dest="services",
        help="Runtime service that must be inactive before mutating; may be repeated.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    manifest = run(
        db_path=Path(args.db_path),
        target_date=date.fromisoformat(str(args.target_date)),
        execute_archive=bool(args.execute_archive),
        build_compact=bool(args.compact),
        swap_compact=bool(args.swap),
        checkpoint=bool(args.checkpoint),
        prune_rollbacks=bool(args.prune_rollbacks),
        compact_path=Path(args.compact_path) if args.compact_path else None,
        archive_root=Path(args.archive_root),
        manifest_dir=Path(args.manifest_dir),
        chunk_size=max(1, int(args.chunk_size)),
        max_chunks=max(0, int(args.max_chunks)),
        rollback_retention_days=max(0, int(args.rollback_retention_days)),
        # Hard floor of 1: a swap must always leave at least one rollback copy.
        rollback_min_keep=max(1, int(args.rollback_min_keep)),
        skip_training_evidence=bool(args.skip_training_evidence),
        force=bool(args.force),
        skip_market_hours_check=bool(args.skip_market_hours_check),
        skip_service_check=bool(args.skip_service_check),
        service_names=tuple(args.services or sqlite_vacuum_swap.DEFAULT_SERVICE_NAMES),
        dbstat_limit=max(0, int(args.dbstat_limit)),
        dbstat_timeout_sec=max(0.1, float(args.dbstat_timeout_sec)),
        skip_backup_check=bool(args.skip_backup_check),
        require_backup_max_age_hours=max(0.0, float(args.require_backup_max_age_hours)),
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest.get("status") in {"complete", "complete_with_warnings"} else 2


if __name__ == "__main__":
    raise SystemExit(main())
