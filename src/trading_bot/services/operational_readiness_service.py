"""Aggregated operational readiness gate for deploy and market-session checks."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from repositories.job_runs_repo import JobRunsRepository
from services.config_audit_service import build_config_audit_payload
from services.job_runs_service import JobRunsService
from services.packaged_entrypoint_validation_service import (
    build_packaged_entrypoint_validation_payload,
)

OPERATIONAL_READINESS_VERSION = "operational_readiness_v1"
OPERATIONAL_READINESS_RUNTIME_EFFECT = "diagnostic_only_no_runtime_change"


@dataclass(frozen=True)
class OperationalCheck:
    name: str
    status: str
    severity: str
    summary: str
    detail: dict[str, Any]

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    @property
    def critical(self) -> bool:
        return self.severity == "critical" and not self.ok

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _age_hours(path: Path | None) -> float | None:
    if path is None or not path.exists():
        return None
    return round((datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) / 3600, 2)


def _latest_backup_manifest(base_dir: Path) -> tuple[Path | None, dict[str, Any] | None]:
    backup_dir = base_dir / "backups" / "databases"
    manifests = sorted(
        backup_dir.glob("**/database_backup_*.manifest.json"),
        key=lambda p: p.stat().st_mtime,
    )
    if not manifests:
        return None, None
    path = manifests[-1]
    try:
        return path, json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return path, None


def _backup_check(base_dir: Path, *, max_age_hours: float) -> OperationalCheck:
    path, manifest = _latest_backup_manifest(base_dir)
    age = _age_hours(path)
    if manifest is None:
        return OperationalCheck(
            name="database_backup",
            status="fail",
            severity="critical",
            summary="no readable database backup manifest",
            detail={"manifest_path": str(path) if path else None, "age_hours": age},
        )
    summary = manifest.get("summary") or {}
    failed = int(summary.get("failed_count") or 0)
    backed_up = int(summary.get("backed_up_count") or 0)
    reused = int(summary.get("reused_count") or 0)
    stale = age is None or age > max_age_hours
    ok = failed == 0 and (backed_up + reused) > 0 and not stale
    return OperationalCheck(
        name="database_backup",
        status="ok" if ok else "fail",
        severity="critical",
        summary=(
            "latest database backup is fresh and verified"
            if ok
            else "latest database backup is stale, failed, or verified zero DBs"
        ),
        detail={
            "manifest_path": str(path),
            "age_hours": age,
            "max_age_hours": max_age_hours,
            "backed_up_count": backed_up,
            "reused_count": reused,
            "failed_count": failed,
            "missing_count": int(summary.get("missing_count") or 0),
        },
    )


def _entrypoint_check(base_dir: Path) -> OperationalCheck:
    required = ["app.py", "db_migrations.py", "ops_check.py", "scripts/job_runner.py"]
    missing = [name for name in required if not (base_dir / name).exists()]
    return OperationalCheck(
        name="critical_entrypoints",
        status="ok" if not missing else "fail",
        severity="critical",
        summary="critical repo entrypoints exist"
        if not missing
        else "critical entrypoints missing",
        detail={"required": required, "missing": missing},
    )


def _packaged_entrypoints_check(base_dir: Path) -> OperationalCheck:
    payload = build_packaged_entrypoint_validation_payload(base_dir=base_dir)
    ready = bool(payload.get("ready"))
    return OperationalCheck(
        name="packaged_entrypoints",
        status="ok" if ready else "fail",
        severity="critical",
        summary="packaged runtime entrypoints import" if ready else "packaged entrypoints failed",
        detail={
            "failed_count": payload.get("failed_count"),
            "check_count": payload.get("check_count"),
            "checks": payload.get("checks"),
        },
    )


def _config_check(base_dir: Path, env: dict[str, str] | None) -> OperationalCheck:
    payload = build_config_audit_payload(base_dir=base_dir, env=env)
    factory_failures = int(payload.get("factory_failures") or 0)
    warnings = list(payload.get("warnings") or [])
    critical = factory_failures > 0
    status = "fail" if critical else ("warn" if warnings else "ok")
    return OperationalCheck(
        name="config_safety",
        status=status,
        severity="critical" if critical else "warning",
        summary=(
            "config factories and runtime safety are clean"
            if status == "ok"
            else "config audit has warnings or factory failures"
        ),
        detail={
            "factory_failures": factory_failures,
            "warnings": warnings,
            "runtime_safety_profile": payload.get("runtime_safety_profile"),
        },
    )


def _secrets_file_check(env_file: Path) -> OperationalCheck:
    if not env_file.exists():
        return OperationalCheck(
            name="local_secret_file",
            status="warn",
            severity="warning",
            summary="local env file is missing; external secret manager may be in use",
            detail={"env_file": str(env_file), "exists": False},
        )
    mode = env_file.stat().st_mode & 0o777
    unsafe = bool(mode & 0o077)
    return OperationalCheck(
        name="local_secret_file",
        status="fail" if unsafe else "ok",
        severity="critical",
        summary="local env file permissions are safe"
        if not unsafe
        else "env file is group/world accessible",
        detail={"env_file": str(env_file), "exists": True, "mode": oct(mode)},
    )


def _job_ledger_check(
    *,
    base_dir: Path,
    target_date: str,
    require_job_ledger: bool,
) -> OperationalCheck:
    db_path = base_dir / "trades.db"
    if not db_path.exists():
        return OperationalCheck(
            name="runtime_job_ledger",
            status="fail",
            severity="critical",
            summary="trades.db missing; runtime job ledger unavailable",
            detail={"db_path": str(db_path)},
        )
    service = JobRunsService(JobRunsRepository(db_path))
    payload = service.health_payload(target_date=target_date)
    clean = bool(payload.summary.get("clean"))
    has_rows = bool(payload.rows)
    if clean and has_rows:
        status = "ok"
        severity = "critical"
        summary = "runtime job ledger is clean"
    elif not has_rows and not require_job_ledger:
        status = "warn"
        severity = "warning"
        summary = "no runtime job rows for date; allowed by non-strict mode"
    else:
        status = "fail"
        severity = "critical"
        summary = "runtime job ledger has gaps or failures"
    return OperationalCheck(
        name="runtime_job_ledger",
        status=status,
        severity=severity,
        summary=summary,
        detail={
            "target_date": target_date,
            "total_runs": payload.summary.get("total_runs"),
            "failed": payload.summary.get("failed"),
            "launcher_errors": payload.summary.get("launcher_errors"),
            "warnings_count": payload.summary.get("warnings_count"),
            "consecutive_failure_jobs": payload.summary.get("consecutive_failure_jobs"),
        },
    )


def _sqlite_file_check(base_dir: Path, *, max_wal_bytes: int) -> OperationalCheck:
    db_path = base_dir / "trades.db"
    wal_path = base_dir / "trades.db-wal"
    shm_path = base_dir / "trades.db-shm"
    db_exists = db_path.exists()
    wal_bytes = wal_path.stat().st_size if wal_path.exists() else 0
    status = "ok"
    summary = "SQLite runtime files are present and WAL size is within limit"
    severity = "warning"
    if not db_exists:
        status = "fail"
        severity = "critical"
        summary = "trades.db is missing"
    elif wal_bytes > max_wal_bytes:
        status = "warn"
        summary = "trades.db WAL is large; checkpoint after market session"
    return OperationalCheck(
        name="sqlite_runtime_files",
        status=status,
        severity=severity,
        summary=summary,
        detail={
            "trades_db": str(db_path),
            "trades_db_exists": db_exists,
            "trades_db_bytes": db_path.stat().st_size if db_exists else 0,
            "wal_path": str(wal_path),
            "wal_exists": wal_path.exists(),
            "wal_bytes": wal_bytes,
            "shm_exists": shm_path.exists(),
            "max_wal_bytes": max_wal_bytes,
        },
    )


def _deployment_reference_check(
    missing_references: list[dict[str, Any]] | None,
) -> OperationalCheck:
    missing = list(missing_references or [])
    return OperationalCheck(
        name="deployment_references",
        status="ok" if not missing else "fail",
        severity="critical",
        summary=(
            "cron/systemd deployment references resolve"
            if not missing
            else "cron/systemd deployment references include missing files"
        ),
        detail={"missing_references": missing[:20], "missing_count": len(missing)},
    )


def build_operational_readiness_payload(
    *,
    base_dir: Path,
    target_date: str,
    env_file: Path = Path("/etc/trading-bot.env"),
    env: dict[str, str] | None = None,
    max_backup_age_hours: float = 30.0,
    max_wal_bytes: int = 512 * 1024 * 1024,
    require_job_ledger: bool = True,
    missing_deployment_references: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    checks = [
        _entrypoint_check(base_dir),
        _packaged_entrypoints_check(base_dir),
        _config_check(base_dir, env),
        _secrets_file_check(env_file),
        _backup_check(base_dir, max_age_hours=max_backup_age_hours),
        _job_ledger_check(
            base_dir=base_dir,
            target_date=target_date,
            require_job_ledger=require_job_ledger,
        ),
        _sqlite_file_check(base_dir, max_wal_bytes=max_wal_bytes),
        _deployment_reference_check(missing_deployment_references),
    ]
    critical_failures = [check for check in checks if check.critical]
    warnings = [check for check in checks if check.status == "warn"]
    return {
        "report_version": OPERATIONAL_READINESS_VERSION,
        "runtime_effect": OPERATIONAL_READINESS_RUNTIME_EFFECT,
        "target_date": target_date,
        "ready": not critical_failures,
        "check_count": len(checks),
        "critical_failure_count": len(critical_failures),
        "warning_count": len(warnings),
        "checks": [check.to_dict() for check in checks],
    }
