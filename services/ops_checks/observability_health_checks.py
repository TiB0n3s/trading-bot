"""Lightweight operational observability summary."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from repositories.job_runs_repo import JobRunsRepository
from runtime_config import public_ml_authority_config
from services.job_runs_service import JobRunsService


def _latest_backup_summary(base_dir: Path) -> dict[str, Any]:
    backup_dir = base_dir / "backups" / "databases"
    manifests = sorted(backup_dir.glob("database_backup_*.manifest.json"))
    if not manifests:
        return {
            "status": "missing_manifest",
            "ok": False,
            "path": None,
            "age_hours": None,
        }
    path = manifests[-1]
    age_hours = round((datetime.now(timezone.utc).timestamp() - path.stat().st_mtime) / 3600, 2)
    try:
        payload = json.loads(path.read_text())
    except Exception as exc:
        return {
            "status": "unreadable_manifest",
            "ok": False,
            "path": str(path),
            "age_hours": age_hours,
            "error": f"{type(exc).__name__}: {exc}",
        }
    summary = payload.get("summary") or {}
    return {
        "status": "ok" if summary.get("ok") else "not_ok",
        "ok": bool(summary.get("ok")),
        "path": str(path),
        "age_hours": age_hours,
        "backed_up_count": summary.get("backed_up_count"),
        "failed_count": summary.get("failed_count"),
        "missing_count": summary.get("missing_count"),
    }


def _service_watchdog_summary(base_dir: Path, *, max_lines: int = 200) -> dict[str, Any]:
    path = base_dir / "service_health.log"
    if not path.exists():
        return {"status": "missing_log", "warnings": 0, "path": str(path)}
    try:
        lines = path.read_text(errors="replace").splitlines()[-max_lines:]
    except OSError as exc:
        return {
            "status": "unreadable_log",
            "warnings": 0,
            "path": str(path),
            "error": f"{type(exc).__name__}: {exc}",
        }
    warnings = [line for line in lines if "WARNING" in line.upper()]
    return {
        "status": "warnings" if warnings else "ok",
        "warnings": len(warnings),
        "path": str(path),
        "latest_warning": warnings[-1] if warnings else None,
    }


def _job_ledger_summary(target_date: str, base_dir: Path) -> dict[str, Any]:
    db_path = base_dir / "trades.db"
    if not db_path.exists():
        return {"status": "missing_db", "ok": False, "db_path": str(db_path)}
    service = JobRunsService(JobRunsRepository(db_path))
    payload = service.health_payload(target_date=target_date)
    summary = payload.summary
    return {
        "status": "ok" if summary.get("clean") else "not_ok",
        "ok": bool(summary.get("clean")),
        "runs": summary.get("total_runs"),
        "failed": summary.get("failed"),
        "launcher_errors": summary.get("launcher_errors"),
        "warnings_count": summary.get("warnings_count"),
        "consecutive_failure_jobs": summary.get("consecutive_failure_jobs") or [],
    }


def _model_staleness_summary() -> dict[str, Any]:
    config = public_ml_authority_config()
    guard = config.get("model_staleness_guard") or {}
    return {
        "authority_mode": config.get("authority_mode"),
        "model_id": config.get("model_id"),
        "fallback_required": bool(guard.get("fallback_required")),
        "guard_status": guard.get("status"),
        "reason": guard.get("reason"),
    }


def run_observability_health(target_date: str, *, base_dir: Path) -> bool:
    job_ledger = _job_ledger_summary(target_date, base_dir)
    backups = _latest_backup_summary(base_dir)
    watchdog = _service_watchdog_summary(base_dir)
    model = _model_staleness_summary()

    critical = []
    warnings = []
    if not job_ledger.get("ok"):
        critical.append("job_ledger_not_clean")
    if not backups.get("ok"):
        warnings.append("database_backup_not_fresh_or_not_verified")
    if watchdog.get("warnings"):
        warnings.append("service_watchdog_recent_warnings")
    if model.get("fallback_required") and model.get("authority_mode") not in (
        "observe_only_compare",
        "disabled",
    ):
        critical.append("ml_authority_model_staleness_fallback_required")

    print()
    print("=" * 72)
    print(f"  Observability Health — {target_date}")
    print("=" * 72)
    print("report_version          : observability_health_v1")
    print("runtime_effect          : diagnostic_only_no_runtime_change")

    print()
    print("Job ledger")
    print(f"  status                : {job_ledger.get('status')}")
    print(f"  runs                  : {job_ledger.get('runs', '-')}")
    print(f"  failed                : {job_ledger.get('failed', '-')}")
    print(f"  launcher_errors       : {job_ledger.get('launcher_errors', '-')}")
    print(f"  warnings_count        : {job_ledger.get('warnings_count', '-')}")

    print()
    print("Database backups")
    print(f"  status                : {backups.get('status')}")
    print(f"  latest_manifest       : {backups.get('path') or '-'}")
    print(
        f"  age_hours             : {backups.get('age_hours') if backups.get('age_hours') is not None else '-'}"
    )
    print(f"  failed_count          : {backups.get('failed_count', '-')}")

    print()
    print("Service watchdog")
    print(f"  status                : {watchdog.get('status')}")
    print(f"  warnings              : {watchdog.get('warnings')}")
    print(f"  latest_warning        : {watchdog.get('latest_warning') or '-'}")

    print()
    print("ML staleness guard")
    print(f"  authority_mode        : {model.get('authority_mode')}")
    print(f"  model_id              : {model.get('model_id') or '-'}")
    print(f"  guard_status          : {model.get('guard_status')}")
    print(f"  fallback_required     : {model.get('fallback_required')}")

    print()
    if critical:
        print(f"[FAIL] critical observability findings: {', '.join(critical)}")
        return False
    if warnings:
        print(f"[WARN] observability warnings: {', '.join(warnings)}")
        return False
    print("[OK] observability health is clean")
    return True
