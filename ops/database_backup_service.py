"""SQLite backup and restore-verification service.

This service uses SQLite's online backup API so WAL-mode databases can be copied
without relying on shell-only `sqlite3 .backup` commands.
"""

from __future__ import annotations

import json
import sqlite3
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

DEFAULT_DB_NAMES = ("trades.db", "jobs.db")
DEFAULT_BACKUP_TIER = "adhoc"
BACKUP_TIER_RETENTION_DAYS = {
    "son": 7,
    "father": 28,
    "grandfather": 2555,
    "adhoc": 30,
}
RESTORABLE_BACKUP_STATUSES = {
    "verified",
    "reused_recent_full",
    "reused_recent_existing_full",
}


def utc_stamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _normalize_backup_tier(value: str | None) -> str:
    tier = (value or DEFAULT_BACKUP_TIER).strip().lower()
    if tier not in BACKUP_TIER_RETENTION_DAYS:
        allowed = ", ".join(sorted(BACKUP_TIER_RETENTION_DAYS))
        raise ValueError(f"unknown backup tier {tier!r}; expected one of: {allowed}")
    return tier


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
    backup_tier: str
    retention_days: int
    dry_run: bool
    results: list[DatabaseBackupResult]
    pruned_files: list[str]

    @property
    def backed_up_count(self) -> int:
        return sum(1 for row in self.results if row.status == "verified")

    @property
    def reused_count(self) -> int:
        return sum(1 for row in self.results if row.status.startswith("reused_recent"))

    @property
    def failed_count(self) -> int:
        return sum(1 for row in self.results if row.status == "failed")

    @property
    def missing_count(self) -> int:
        return sum(1 for row in self.results if row.status == "missing")

    @property
    def ok(self) -> bool:
        return self.failed_count == 0 and (self.backed_up_count + self.reused_count) > 0

    def to_dict(self) -> dict:
        payload = asdict(self)
        payload["summary"] = {
            "ok": self.ok,
            "backed_up_count": self.backed_up_count,
            "reused_count": self.reused_count,
            "failed_count": self.failed_count,
            "missing_count": self.missing_count,
        }
        return payload


@dataclass(frozen=True)
class DatabaseRestoreDrillResult:
    name: str
    backup_path: str | None
    restore_path: str | None
    status: str
    integrity_check: str | None = None
    table_count: int | None = None
    duration_sec: float | None = None
    error: str | None = None


@dataclass(frozen=True)
class DatabaseRestoreDrillManifest:
    report_version: str
    runtime_effect: str
    created_at: str
    backup_manifest_path: str | None
    restore_dir: str
    results: list[DatabaseRestoreDrillResult]

    @property
    def verified_count(self) -> int:
        return sum(1 for row in self.results if row.status == "verified")

    @property
    def failed_count(self) -> int:
        return sum(1 for row in self.results if row.status == "failed")

    @property
    def skipped_count(self) -> int:
        return sum(1 for row in self.results if row.status == "skipped")

    @property
    def ok(self) -> bool:
        return self.failed_count == 0 and self.verified_count > 0

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["summary"] = {
            "ok": self.ok,
            "verified_count": self.verified_count,
            "failed_count": self.failed_count,
            "skipped_count": self.skipped_count,
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
        skip_recent_full_hours: float | None = None,
        backup_tier: str = DEFAULT_BACKUP_TIER,
    ) -> DatabaseBackupManifest:
        stamp = timestamp or utc_stamp()
        tier = _normalize_backup_tier(backup_tier)
        results: list[DatabaseBackupResult] = []

        for name in db_names:
            results.append(
                self._backup_one(
                    name=name,
                    timestamp=stamp,
                    dry_run=dry_run,
                    skip_recent_full_hours=skip_recent_full_hours,
                    backup_tier=tier,
                )
            )

        pruned_files = self._prune_old_backups(
            retention_days=retention_days,
            dry_run=dry_run,
            backup_tier=tier,
        )
        return DatabaseBackupManifest(
            report_version="database_backup_manifest_v1",
            runtime_effect="filesystem_backup_only_no_trading_authority",
            created_at=datetime.now(timezone.utc).isoformat(),
            backup_dir=str(self.backup_dir),
            backup_tier=tier,
            retention_days=retention_days,
            dry_run=dry_run,
            results=results,
            pruned_files=pruned_files,
        )

    def write_manifest(self, manifest: DatabaseBackupManifest) -> Path:
        root = self._tier_root(_normalize_backup_tier(manifest.backup_tier))
        root.mkdir(parents=True, exist_ok=True)
        path = root / f"database_backup_{utc_stamp()}.manifest.json"
        path.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n")
        return path

    def _backup_one(
        self,
        *,
        name: str,
        timestamp: str,
        dry_run: bool,
        skip_recent_full_hours: float | None,
        backup_tier: str,
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
        backup_path = self._tier_root(backup_tier) / timestamp / name
        recent = self._recent_full_backup(
            name,
            max_age_hours=skip_recent_full_hours,
            min_size_bytes=int(source_size * 0.8),
        )
        if recent is not None and not dry_run:
            recent_path, recent_row, status = recent
            return DatabaseBackupResult(
                name=name,
                source_path=str(source),
                backup_path=str(recent_path),
                source_exists=True,
                status=status,
                source_size_bytes=source_size,
                backup_size_bytes=recent_path.stat().st_size if recent_path.exists() else None,
                integrity_check=recent_row.get("integrity_check"),
                table_count=recent_row.get("table_count"),
                error=(
                    "recent full backup reused; no new full copy attempted "
                    f"within {skip_recent_full_hours:.1f}h window"
                ),
            )
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

    def _recent_full_backup(
        self,
        name: str,
        *,
        max_age_hours: float | None,
        min_size_bytes: int,
    ) -> tuple[Path, dict[str, Any], str] | None:
        if max_age_hours is None or max_age_hours <= 0 or not self.backup_dir.exists():
            return None

        max_age_seconds = max_age_hours * 60 * 60
        now = time.time()
        manifests = sorted(self.backup_dir.glob("**/database_backup_*.manifest.json"), reverse=True)
        for manifest_path in manifests:
            try:
                manifest = json.loads(manifest_path.read_text())
            except Exception:
                continue
            for row in manifest.get("results", []):
                if row.get("name") != name or row.get("status") != "verified":
                    continue
                backup_path = Path(str(row.get("backup_path") or ""))
                if not backup_path.exists():
                    continue
                if now - backup_path.stat().st_mtime > max_age_seconds:
                    continue
                return backup_path, row, "reused_recent_full"

        candidates = []
        for backup_path in self.backup_dir.glob(f"**/{name}"):
            if "restore_drills" in backup_path.parts:
                continue
            try:
                stat = backup_path.stat()
            except OSError:
                continue
            if stat.st_size < min_size_bytes:
                continue
            if now - stat.st_mtime > max_age_seconds:
                continue
            candidates.append((stat.st_mtime, backup_path))

        if candidates:
            _, backup_path = sorted(candidates, reverse=True)[0]
            return (
                backup_path,
                {
                    "integrity_check": "not_rechecked_existing_full",
                    "table_count": None,
                },
                "reused_recent_existing_full",
            )
        return None

    def _prune_old_backups(
        self,
        *,
        retention_days: int,
        dry_run: bool,
        backup_tier: str,
    ) -> list[str]:
        root = self._tier_root(backup_tier)
        if retention_days <= 0 or not root.exists():
            return []

        cutoff = time.time() - (retention_days * 24 * 60 * 60)
        pruned: list[str] = []
        for path in sorted(root.glob("**/*.db")):
            if "restore_drills" in path.parts:
                continue
            try:
                if path.stat().st_mtime >= cutoff:
                    continue
                pruned.append(str(path))
                if not dry_run:
                    path.unlink()
            except OSError:
                continue
        return pruned

    def _tier_root(self, backup_tier: str) -> Path:
        if backup_tier == DEFAULT_BACKUP_TIER:
            return self.backup_dir
        return self.backup_dir / backup_tier


class DatabaseRestoreDrillService:
    """Verify latest backup artifacts can be restored into readable SQLite files."""

    def __init__(self, *, backup_dir: Path):
        self.backup_dir = Path(backup_dir)

    def run(
        self,
        *,
        manifest_path: Path | None = None,
        restore_dir: Path | None = None,
    ) -> DatabaseRestoreDrillManifest:
        source_manifest_path, source_manifest = self._load_manifest(manifest_path)
        owned_temp: tempfile.TemporaryDirectory[str] | None = None
        if restore_dir is None:
            owned_temp = tempfile.TemporaryDirectory(prefix="trading_bot_restore_drill_")
            restore_root = Path(owned_temp.name)
        else:
            restore_root = Path(restore_dir)
            restore_root.mkdir(parents=True, exist_ok=True)

        try:
            results = self._verify_rows(source_manifest, restore_root)
            return DatabaseRestoreDrillManifest(
                report_version="database_restore_drill_v1",
                runtime_effect="restore_verification_only_no_runtime_change",
                created_at=datetime.now(timezone.utc).isoformat(),
                backup_manifest_path=str(source_manifest_path) if source_manifest_path else None,
                restore_dir=str(restore_root),
                results=results,
            )
        finally:
            if owned_temp is not None:
                owned_temp.cleanup()

    def write_manifest(self, manifest: DatabaseRestoreDrillManifest) -> Path:
        drill_dir = self.backup_dir / "restore_drills"
        drill_dir.mkdir(parents=True, exist_ok=True)
        path = drill_dir / f"database_restore_drill_{utc_stamp()}.manifest.json"
        path.write_text(json.dumps(manifest.to_dict(), indent=2, sort_keys=True) + "\n")
        return path

    def _load_manifest(
        self,
        manifest_path: Path | None,
    ) -> tuple[Path | None, dict[str, Any] | None]:
        if manifest_path is None:
            manifests = sorted(self.backup_dir.glob("**/database_backup_*.manifest.json"))
            manifest_path = manifests[-1] if manifests else None
        if manifest_path is None or not manifest_path.exists():
            return manifest_path, None
        try:
            loaded = json.loads(manifest_path.read_text())
            return manifest_path, loaded if isinstance(loaded, dict) else None
        except Exception:
            return manifest_path, None

    def _verify_rows(
        self,
        manifest: dict[str, Any] | None,
        restore_root: Path,
    ) -> list[DatabaseRestoreDrillResult]:
        if not manifest:
            return [
                DatabaseRestoreDrillResult(
                    name="manifest",
                    backup_path=None,
                    restore_path=None,
                    status="failed",
                    error="no readable database backup manifest",
                )
            ]

        results: list[DatabaseRestoreDrillResult] = []
        for row in manifest.get("results") or []:
            name = str(row.get("name") or "unknown.db")
            backup_path = Path(str(row.get("backup_path") or ""))
            if row.get("status") not in RESTORABLE_BACKUP_STATUSES or not row.get("backup_path"):
                results.append(
                    DatabaseRestoreDrillResult(
                        name=name,
                        backup_path=str(row.get("backup_path") or ""),
                        restore_path=None,
                        status="skipped",
                        error=f"backup row status is {row.get('status') or 'unknown'}",
                    )
                )
                continue
            restore_path = restore_root / name
            started = time.monotonic()
            try:
                if not backup_path.exists():
                    raise FileNotFoundError(str(backup_path))
                restore_path.parent.mkdir(parents=True, exist_ok=True)
                if restore_path.exists():
                    restore_path.unlink()
                with sqlite3.connect(backup_path) as src:
                    with sqlite3.connect(restore_path) as dst:
                        src.backup(dst)
                integrity_check, table_count = DatabaseBackupService.verify_backup(restore_path)
                results.append(
                    DatabaseRestoreDrillResult(
                        name=name,
                        backup_path=str(backup_path),
                        restore_path=str(restore_path),
                        status="verified" if integrity_check == "ok" else "failed",
                        integrity_check=integrity_check,
                        table_count=table_count,
                        duration_sec=round(time.monotonic() - started, 3),
                    )
                )
            except Exception as exc:
                results.append(
                    DatabaseRestoreDrillResult(
                        name=name,
                        backup_path=str(backup_path),
                        restore_path=str(restore_path),
                        status="failed",
                        duration_sec=round(time.monotonic() - started, 3),
                        error=f"{type(exc).__name__}: {exc}",
                    )
                )
        return results
