"""SQLite backup and restore-verification service.

This service uses SQLite's online backup API so WAL-mode databases can be copied
without relying on shell-only `sqlite3 .backup` commands.
"""

from __future__ import annotations

import json
import sqlite3
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable

DEFAULT_DB_NAMES = ("trades.db", "predictions.db", "jobs.db")


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


@dataclass(frozen=True)
class DatabaseBackupResult:
    name: str
    source_path: str
    backup_path: str | None
    source_exists: bool
    status: str
    source_size_bytes: int | None = None
    backup_size_bytes: int | None = None
    integrity_check: str | None = None
    table_count: int | None = None
    duration_sec: float | None = None
    error: str | None = None


@dataclass(frozen=True)
class DatabaseBackupManifest:
    report_version: str
    runtime_effect: str
    created_at: str
    backup_dir: str
    retention_days: int
    dry_run: bool
    results: list[DatabaseBackupResult]
    pruned_files: list[str]

    @property
    def backed_up_count(self) -> int:
        return sum(1 for row in self.results if row.status == "verified")

    @property
    def failed_count(self) -> int:
        return sum(1 for row in self.results if row.status == "failed")

    @property
    def missing_count(self) -> int:
        return sum(1 for row in self.results if row.status == "missing")

    @property
    def ok(self) -> bool:
        return self.failed_count == 0 and self.backed_up_count > 0

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["summary"] = {
            "ok": self.ok,
            "backed_up_count": self.backed_up_count,
            "failed_count": self.failed_count,
            "missing_count": self.missing_count,
        }
        return payload


class DatabaseBackupService:
    def __init__(self, *, base_dir: Path, backup_dir: Path):
        self.base_dir = Path(base_dir)
        self.backup_dir = Path(backup_dir)

    def run(
        self,
        *,
        db_names: Iterable[str] = DEFAULT_DB_NAMES,
        retention_days: int = 30,
        timestamp: str | None = None,
        dry_run: bool = False,
    ) -> DatabaseBackupManifest:
        stamp = timestamp or utc_stamp()
        results: list[DatabaseBackupResult] = []

        for name in db_names:
            results.append(
                self._backup_one(
                    name=name,
                    timestamp=stamp,
                    dry_run=dry_run,
                )
            )

        pruned_files = self._prune_old_backups(retention_days=retention_days, dry_run=dry_run)
        return DatabaseBackupManifest(
            report_version="database_backup_manifest_v1",
            runtime_effect="filesystem_backup_only_no_trading_authority",
            created_at=datetime.now(timezone.utc).isoformat(),
            backup_dir=str(self.backup_dir),
            retention_days=retention_days,
            dry_run=dry_run,
            results=results,
            pruned_files=pruned_files,
        )

    def write_manifest(self, manifest: DatabaseBackupManifest) -> Path:
        self.backup_dir.mkdir(parents=True, exist_ok=True)
        path = self.backup_dir / f"database_backup_{utc_stamp()}.manifest.json"
        path.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n")
        return path

    def _backup_one(
        self,
        *,
        name: str,
        timestamp: str,
        dry_run: bool,
    ) -> DatabaseBackupResult:
        source = self.base_dir / name
        if not source.exists():
            return DatabaseBackupResult(
                name=name,
                source_path=str(source),
                backup_path=None,
                source_exists=False,
                status="missing",
            )

        source_size = source.stat().st_size
        backup_path = self.backup_dir / timestamp / name
        if dry_run:
            return DatabaseBackupResult(
                name=name,
                source_path=str(source),
                backup_path=str(backup_path),
                source_exists=True,
                status="dry_run",
                source_size_bytes=source_size,
            )

        started = time.monotonic()
        try:
            backup_path.parent.mkdir(parents=True, exist_ok=True)
            self._sqlite_backup(source, backup_path)
            integrity_check, table_count = self.verify_backup(backup_path)
            return DatabaseBackupResult(
                name=name,
                source_path=str(source),
                backup_path=str(backup_path),
                source_exists=True,
                status="verified" if integrity_check == "ok" else "failed",
                source_size_bytes=source_size,
                backup_size_bytes=backup_path.stat().st_size,
                integrity_check=integrity_check,
                table_count=table_count,
                duration_sec=round(time.monotonic() - started, 3),
            )
        except Exception as exc:
            return DatabaseBackupResult(
                name=name,
                source_path=str(source),
                backup_path=str(backup_path),
                source_exists=True,
                status="failed",
                source_size_bytes=source_size,
                duration_sec=round(time.monotonic() - started, 3),
                error=f"{type(exc).__name__}: {exc}",
            )

    @staticmethod
    def _sqlite_backup(source: Path, destination: Path) -> None:
        if destination.exists():
            destination.unlink()
        with sqlite3.connect(source) as src:
            with sqlite3.connect(destination) as dst:
                src.backup(dst)

    @staticmethod
    def verify_backup(path: Path) -> tuple[str, int]:
        with sqlite3.connect(path) as con:
            integrity_check = str(con.execute("PRAGMA integrity_check").fetchone()[0])
            table_count = int(
                con.execute(
                    """
                    SELECT COUNT(*)
                    FROM sqlite_master
                    WHERE type = 'table'
                    """
                ).fetchone()[0]
            )
        return integrity_check, table_count

    def _prune_old_backups(self, *, retention_days: int, dry_run: bool) -> list[str]:
        if retention_days <= 0 or not self.backup_dir.exists():
            return []

        cutoff = time.time() - (retention_days * 24 * 60 * 60)
        pruned: list[str] = []
        for path in sorted(self.backup_dir.glob("**/*.db")):
            try:
                if path.stat().st_mtime >= cutoff:
                    continue
                pruned.append(str(path))
                if not dry_run:
                    path.unlink()
            except OSError:
                continue
        return pruned
