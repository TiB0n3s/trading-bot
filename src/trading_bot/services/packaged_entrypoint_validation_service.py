"""Validate packaged runtime entrypoints before root-shim reduction."""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Any


def build_packaged_entrypoint_validation_payload(*, base_dir: Path) -> dict[str, Any]:
    checks: list[dict[str, Any]] = []

    def add(name: str, passed: bool, detail: str) -> None:
        checks.append({"name": name, "passed": bool(passed), "detail": detail})

    app_path = base_dir / "app.py"
    line_count = app_path.read_text(encoding="utf-8").count("\n") + 1 if app_path.exists() else 0
    add("root_app_exists", app_path.exists(), str(app_path))
    add("root_app_under_1500_lines", line_count < 1500, f"{line_count} lines")

    try:
        app_factory = importlib.import_module("trading_bot.web.app_factory")
        add(
            "package_app_factory_importable",
            hasattr(app_factory, "create_runtime_flask_app"),
            "create_runtime_flask_app present",
        )
    except Exception as exc:
        add("package_app_factory_importable", False, f"{type(exc).__name__}: {exc}")

    try:
        startup = importlib.import_module("trading_bot.runtime.startup")
        add(
            "package_startup_importable",
            hasattr(startup, "run_runtime_startup_tasks"),
            "run_runtime_startup_tasks present",
        )
    except Exception as exc:
        add("package_startup_importable", False, f"{type(exc).__name__}: {exc}")

    wsgi_path = base_dir / "wsgi.py"
    if wsgi_path.exists():
        wsgi_source = wsgi_path.read_text(encoding="utf-8")
        add(
            "wsgi_application_declared",
            "application =" in wsgi_source and "create_app(" in wsgi_source,
            str(wsgi_path),
        )
    else:
        add("wsgi_application_declared", False, str(wsgi_path))

    plan_path = base_dir / "ops" / "compatibility_deletion_plan.md"
    add("compatibility_deletion_plan_present", plan_path.exists(), str(plan_path))
    failed = [row for row in checks if not row["passed"]]
    return {
        "report_version": "packaged_entrypoint_validation_v1",
        "runtime_effect": "diagnostic_only_import_validation_no_startup",
        "check_count": len(checks),
        "failed_count": len(failed),
        "checks": checks,
        "ready": not failed,
    }
