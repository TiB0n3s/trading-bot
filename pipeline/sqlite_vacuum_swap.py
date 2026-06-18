#!/usr/bin/env python3
"""Build and optionally swap a compact SQLite database with VACUUM INTO.

The default mode is a read-only plan. Use ``--build`` to create a compact copy.
Use ``--swap`` only during a planned downtime window after runtime services are
stopped. The original DB is retained as a timestamped rollback file.
"""

from __future__ import annotations

import argparse
import json
import shutil
import sqlite3
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_DB_PATH = ROOT / "trades.db"
DEFAULT_COMPACT_DIR = ROOT / "data_archive" / "sqlite_compact"
DEFAULT_MANIFEST_DIR = ROOT / "data_archive" / "manifests"
DEFAULT_SERVICE_NAMES = (
    "trading-bot",
    "fill-stream",
    "fill-poller",
    "live-bar-stream",
)


@dataclass(frozen=True)
class DbStats:
    path: str
    exists: bool
    size_bytes: int
    page_count: int | None = None
    freelist_count: int | None = None
    page_size: int | None = None
    journal_mode: str | None = None
    table_count: int | None = None
    reclaimable_bytes: int | None = None
    estimated_compact_bytes: int | None = None
    quick_check: str | None = None
    error: str | None = None


def _utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _quote_sql_string(value: Path | str) -> str:
    text = str(value)
    return "'" + text.replace("'", "''") + "'"


def _db_stats(path: Path, *, quick_check: bool = False) -> DbStats:
    if not path.exists():
        return DbStats(path=str(path), exists=False, size_bytes=0)
    try:
        with sqlite3.connect(path, timeout=5) as con:
            page_count = int(con.execute("PRAGMA page_count").fetchone()[0])
            freelist_count = int(con.execute("PRAGMA freelist_count").fetchone()[0])
            page_size = int(con.execute("PRAGMA page_size").fetchone()[0])
            journal_mode = str(con.execute("PRAGMA journal_mode").fetchone()[0])
            table_count = int(
                con.execute("SELECT COUNT(*) FROM sqlite_master WHERE type='table'").fetchone()[0]
            )
            check_result = None
            if quick_check:
                check_result = str(con.execute("PRAGMA quick_check").fetchone()[0])
        return DbStats(
            path=str(path),
            exists=True,
            size_bytes=path.stat().st_size,
            page_count=page_count,
            freelist_count=freelist_count,
            page_size=page_size,
            journal_mode=journal_mode,
            table_count=table_count,
            reclaimable_bytes=freelist_count * page_size,
            estimated_compact_bytes=max(0, path.stat().st_size - (freelist_count * page_size)),
            quick_check=check_result,
        )
    except Exception as exc:
        return DbStats(
            path=str(path),
            exists=True,
            size_bytes=path.stat().st_size if path.exists() else 0,
            error=str(exc),
        )


def _schema_objects(path: Path) -> set[tuple[str, str]]:
    with sqlite3.connect(path, timeout=5) as con:
        rows = con.execute(
            """
            SELECT type, name
            FROM sqlite_master
            WHERE type IN ('table', 'index', 'trigger', 'view')
              AND name NOT LIKE 'sqlite_%'
            ORDER BY type, name
            """
        ).fetchall()
    return {(str(row[0]), str(row[1])) for row in rows}


def _service_status(name: str) -> dict[str, Any]:
    unit = name if name.endswith(".service") else f"{name}.service"
    systemctl = shutil.which("systemctl")
    if not systemctl:
        return {
            "name": name,
            "unit": unit,
            "status": "unknown",
            "active": False,
            "reason": "systemctl_not_found",
        }
    result = subprocess.run(
        [systemctl, "is-active", unit],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    status = (result.stdout or result.stderr or "").strip() or "unknown"
    return {
        "name": name,
        "unit": unit,
        "status": status,
        "active": result.returncode == 0 and status == "active",
        "returncode": result.returncode,
    }


def _checkpoint_source(db_path: Path) -> dict[str, Any]:
    with sqlite3.connect(db_path, timeout=30) as con:
        con.execute("PRAGMA busy_timeout=30000")
        row = con.execute("PRAGMA wal_checkpoint(TRUNCATE)").fetchone()
    wal = db_path.with_name(db_path.name + "-wal")
    shm = db_path.with_name(db_path.name + "-shm")
    return {
        "busy": row[0] if row else None,
        "log_frames": row[1] if row else None,
        "checkpointed_frames": row[2] if row else None,
        "wal_bytes": wal.stat().st_size if wal.exists() else 0,
        "shm_bytes": shm.stat().st_size if shm.exists() else 0,
    }


def _build_compact_copy(
    *,
    db_path: Path,
    compact_path: Path,
    replace_existing: bool,
) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"source DB not found: {db_path}")
    compact_path.parent.mkdir(parents=True, exist_ok=True)
    if compact_path.exists():
        if replace_existing:
            compact_path.unlink()
        else:
            raise FileExistsError(
                f"compact target already exists: {compact_path}; use --replace-build"
            )
    with sqlite3.connect(db_path, timeout=30) as con:
        con.execute("PRAGMA busy_timeout=30000")
        con.execute(f"VACUUM INTO {_quote_sql_string(compact_path)}")
    source_objects = _schema_objects(db_path)
    compact_objects = _schema_objects(compact_path)
    missing = sorted(source_objects - compact_objects)
    extra = sorted(compact_objects - source_objects)
    quick = _db_stats(compact_path, quick_check=True)
    return {
        "compact_path": str(compact_path),
        "source_schema_object_count": len(source_objects),
        "compact_schema_object_count": len(compact_objects),
        "schema_missing": missing,
        "schema_extra": extra,
        "quick_check": quick.quick_check,
        "compact_stats": quick.__dict__,
    }


def _sidecar_paths(db_path: Path) -> list[Path]:
    return [
        db_path.with_name(db_path.name + "-wal"),
        db_path.with_name(db_path.name + "-shm"),
        db_path.with_suffix(db_path.suffix + "-journal"),
    ]


def _rollback_candidates(db_path: Path) -> list[Path]:
    prefix = f"{db_path.name}.rollback_"
    return sorted(
        (path for path in db_path.parent.glob(f"{prefix}*") if path.is_file()),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )


def prune_rollback_files(
    *,
    db_path: Path,
    retention_days: int,
    min_keep: int,
    dry_run: bool = False,
) -> dict[str, Any]:
    cutoff_ts = time.time() - (max(0, int(retention_days)) * 86400)
    min_keep = max(0, int(min_keep))
    candidates = _rollback_candidates(db_path)
    base_rollbacks = [
        path
        for path in candidates
        if path.name.startswith(f"{db_path.name}.rollback_")
        and "." not in path.name.removeprefix(f"{db_path.name}.rollback_")
    ]
    protected_bases = {path.name for path in base_rollbacks[:min_keep]}
    pruned: list[dict[str, Any]] = []
    retained: list[dict[str, Any]] = []

    for path in candidates:
        stat = path.stat()
        protected = any(
            path.name == base or path.name.startswith(f"{base}.") for base in protected_bases
        )
        row = {
            "path": str(path),
            "size_bytes": stat.st_size,
            "mtime": datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
        }
        if stat.st_mtime >= cutoff_ts or protected:
            row["reason"] = "protected_min_keep" if protected else "within_retention"
            retained.append(row)
            continue
        row["dry_run"] = dry_run
        pruned.append(row)
        if not dry_run:
            path.unlink()

    return {
        "retention_days": int(retention_days),
        "min_keep": min_keep,
        "dry_run": dry_run,
        "candidate_count": len(candidates),
        "pruned_count": len(pruned),
        "pruned_bytes": sum(int(row["size_bytes"]) for row in pruned),
        "retained_count": len(retained),
        "retained_bytes": sum(int(row["size_bytes"]) for row in retained),
        "pruned": pruned,
        "retained": retained,
    }


def _swap_compact_copy(
    *,
    db_path: Path,
    compact_path: Path,
    rollback_path: Path,
    force: bool,
) -> dict[str, Any]:
    if not db_path.exists():
        raise FileNotFoundError(f"source DB not found: {db_path}")
    if not compact_path.exists():
        raise FileNotFoundError(f"compact DB not found: {compact_path}")
    compact_stats = _db_stats(compact_path, quick_check=True)
    if compact_stats.quick_check != "ok" and not force:
        raise RuntimeError(f"compact DB quick_check failed: {compact_stats.quick_check}")
    checkpoint = _checkpoint_source(db_path)
    if checkpoint["wal_bytes"] and not force:
        raise RuntimeError(
            "source WAL still has bytes after checkpoint; stop writers or use --force"
        )
    rollback_path.parent.mkdir(parents=True, exist_ok=True)
    if rollback_path.exists():
        raise FileExistsError(f"rollback path already exists: {rollback_path}")

    moved_sidecars: list[dict[str, str]] = []
    for sidecar in _sidecar_paths(db_path):
        if sidecar.exists():
            target = rollback_path.with_name(rollback_path.name + f".{sidecar.name}")
            sidecar.rename(target)
            moved_sidecars.append({"from": str(sidecar), "to": str(target)})
    db_path.rename(rollback_path)
    compact_path.rename(db_path)
    final_stats = _db_stats(db_path, quick_check=True)
    if final_stats.quick_check != "ok" and not force:
        db_path.rename(compact_path)
        rollback_path.rename(db_path)
        raise RuntimeError(f"swapped DB quick_check failed: {final_stats.quick_check}")
    return {
        "rollback_path": str(rollback_path),
        "moved_sidecars": moved_sidecars,
        "checkpoint": checkpoint,
        "final_stats": final_stats.__dict__,
    }


def run(
    *,
    db_path: Path,
    compact_path: Path,
    manifest_dir: Path,
    build: bool,
    swap: bool,
    replace_build: bool,
    force: bool,
    skip_service_check: bool,
    service_names: tuple[str, ...],
) -> dict[str, Any]:
    stamp = _utc_stamp()
    manifest: dict[str, Any] = {
        "version": "sqlite_vacuum_swap_v1",
        "created_at": _now_iso(),
        "db_path": str(db_path),
        "compact_path": str(compact_path),
        "build_requested": build,
        "swap_requested": swap,
        "replace_build": replace_build,
        "force": force,
        "skip_service_check": skip_service_check,
        "source_stats_before": _db_stats(db_path).__dict__,
        "service_status": [_service_status(name) for name in service_names],
        "actions": [],
    }

    active_services = [row for row in manifest["service_status"] if row.get("active")]
    if swap and active_services and not skip_service_check and not force:
        manifest["status"] = "blocked_active_services"
        manifest["blocked_services"] = active_services
        return manifest

    if build:
        manifest["actions"].append(
            {
                "action": "build_compact_copy",
                "result": _build_compact_copy(
                    db_path=db_path,
                    compact_path=compact_path,
                    replace_existing=replace_build,
                ),
            }
        )

    if swap:
        rollback_path = db_path.with_name(f"{db_path.name}.rollback_{stamp}")
        manifest["actions"].append(
            {
                "action": "swap_compact_copy",
                "result": _swap_compact_copy(
                    db_path=db_path,
                    compact_path=compact_path,
                    rollback_path=rollback_path,
                    force=force,
                ),
            }
        )

    manifest["source_stats_after"] = _db_stats(db_path).__dict__
    manifest["status"] = "complete"
    manifest["finished_at"] = _now_iso()
    manifest_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = manifest_dir / f"sqlite_vacuum_swap_{stamp}.manifest.json"
    manifest["manifest_path"] = str(manifest_path)
    manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding="utf-8")
    return manifest


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db-path", default=str(DEFAULT_DB_PATH))
    parser.add_argument("--compact-dir", default=str(DEFAULT_COMPACT_DIR))
    parser.add_argument("--compact-path")
    parser.add_argument("--manifest-dir", default=str(DEFAULT_MANIFEST_DIR))
    parser.add_argument("--build", action="store_true", help="Run VACUUM INTO compact copy")
    parser.add_argument("--swap", action="store_true", help="Swap compact copy into db path")
    parser.add_argument("--replace-build", action="store_true")
    parser.add_argument("--force", action="store_true")
    parser.add_argument("--skip-service-check", action="store_true")
    parser.add_argument(
        "--service",
        action="append",
        dest="services",
        help="Runtime service to require inactive before swap; may be repeated.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    db_path = Path(args.db_path)
    compact_path = (
        Path(args.compact_path)
        if args.compact_path
        else Path(args.compact_dir) / f"{db_path.name}.compact"
    )
    manifest = run(
        db_path=db_path,
        compact_path=compact_path,
        manifest_dir=Path(args.manifest_dir),
        build=bool(args.build),
        swap=bool(args.swap),
        replace_build=bool(args.replace_build),
        force=bool(args.force),
        skip_service_check=bool(args.skip_service_check),
        service_names=tuple(args.services or DEFAULT_SERVICE_NAMES),
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0 if manifest.get("status") == "complete" else 2


if __name__ == "__main__":
    raise SystemExit(main())
