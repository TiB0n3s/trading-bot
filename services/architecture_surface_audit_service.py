"""Architecture surface inventory for refactor planning.

This service is diagnostic-only. It measures file-count, line-count, and
configuration-sprawl surfaces so cleanup work can be prioritized without
changing runtime behavior.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from services.config_audit_service import discover_env_var_references

ARCHITECTURE_SURFACE_VERSION = "architecture_surface_audit_v1"
ARCHITECTURE_SURFACE_RUNTIME_EFFECT = "diagnostic_only_no_runtime_change"

COUNT_TARGETS = {
    "root_python_files": 5,
    "services_direct_modules": 45,
    "services_ops_check_modules": 20,
    "repository_modules": 30,
}

LINE_COUNT_TARGETS = {
    "app.py": 100,
    "src/trading_bot/ops_checks/cli.py": 500,
    "scripts/auto_buy_manager.py": 500,
    "scripts/position_manager.py": 500,
    "services/approval_service.py": 700,
    "services/context_builder.py": 700,
    "services/live_signal_processor.py": 700,
    "repositories/ops_check_repo.py": 500,
}

SRC_CONTEXTS = (
    "web",
    "runtime",
    "signals",
    "execution",
    "positions",
    "market_data",
    "persistence",
    "intelligence",
    "learning",
    "reporting",
    "ops_checks",
    "config",
    "ml_platform",
)


@dataclass(frozen=True)
class SurfaceMetric:
    name: str
    current: int
    target: int

    @property
    def over_target(self) -> int:
        return max(0, self.current - self.target)

    @property
    def status(self) -> str:
        return "ok" if self.over_target == 0 else "over_target"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["over_target"] = self.over_target
        data["status"] = self.status
        return data


@dataclass(frozen=True)
class LargeFileMetric:
    path: str
    lines: int
    target: int

    @property
    def over_target(self) -> int:
        return max(0, self.lines - self.target)

    @property
    def status(self) -> str:
        return "ok" if self.over_target == 0 else "over_target"

    def to_dict(self) -> dict[str, Any]:
        data = asdict(self)
        data["over_target"] = self.over_target
        data["status"] = self.status
        return data


def _count_files(path: Path, pattern: str = "*.py") -> int:
    if not path.exists():
        return 0
    return sum(1 for item in path.glob(pattern) if item.is_file())


def _line_count(path: Path) -> int:
    if not path.exists():
        return 0
    return path.read_text(errors="ignore").count("\n") + 1


def _top_python_files(base_dir: Path, *, limit: int = 12) -> list[dict[str, Any]]:
    ignored_parts = {".git", "venv", "__pycache__", ".pytest_cache"}
    rows: list[dict[str, Any]] = []
    for path in base_dir.rglob("*.py"):
        rel_parts = path.relative_to(base_dir).parts
        if any(part in ignored_parts for part in rel_parts):
            continue
        rows.append(
            {
                "path": path.relative_to(base_dir).as_posix(),
                "lines": _line_count(path),
            }
        )
    rows.sort(key=lambda item: (-int(item["lines"]), str(item["path"])))
    return rows[:limit]


def _src_skeleton_status(base_dir: Path) -> dict[str, Any]:
    root = base_dir / "src" / "trading_bot"
    contexts = []
    for name in SRC_CONTEXTS:
        path = root / name
        contexts.append(
            {
                "name": name,
                "exists": path.is_dir(),
                "init_exists": (path / "__init__.py").exists(),
            }
        )
    return {
        "root_exists": root.is_dir(),
        "contexts_expected": len(SRC_CONTEXTS),
        "contexts_ready": sum(1 for item in contexts if item["exists"] and item["init_exists"]),
        "contexts": contexts,
    }


def build_architecture_surface_payload(*, base_dir: Path) -> dict[str, Any]:
    surface_metrics = [
        SurfaceMetric(
            "root_python_files",
            _count_files(base_dir),
            COUNT_TARGETS["root_python_files"],
        ),
        SurfaceMetric(
            "services_direct_modules",
            _count_files(base_dir / "services"),
            COUNT_TARGETS["services_direct_modules"],
        ),
        SurfaceMetric(
            "services_ops_check_modules",
            _count_files(base_dir / "services" / "ops_checks"),
            COUNT_TARGETS["services_ops_check_modules"],
        ),
        SurfaceMetric(
            "repository_modules",
            _count_files(base_dir / "repositories"),
            COUNT_TARGETS["repository_modules"],
        ),
    ]
    large_files = [
        LargeFileMetric(path, _line_count(base_dir / path), target)
        for path, target in LINE_COUNT_TARGETS.items()
    ]
    env_inventory = discover_env_var_references(base_dir)
    src_status = _src_skeleton_status(base_dir)
    over_target_count = sum(1 for item in surface_metrics if item.over_target)
    over_target_count += sum(1 for item in large_files if item.over_target)
    return {
        "version": ARCHITECTURE_SURFACE_VERSION,
        "runtime_effect": ARCHITECTURE_SURFACE_RUNTIME_EFFECT,
        "surface_metrics": [item.to_dict() for item in surface_metrics],
        "large_files": [item.to_dict() for item in large_files],
        "top_python_files": _top_python_files(base_dir),
        "raw_env_files": len(env_inventory["by_file"]),
        "raw_env_keys": env_inventory["total_env_keys"],
        "top_env_access_files": list(env_inventory["by_file"].items())[:10],
        "src_skeleton": src_status,
        "compatibility_plan_exists": (base_dir / "ops" / "compatibility_deletion_plan.md").exists(),
        "over_target_count": over_target_count,
        "ready": over_target_count == 0
        and src_status["contexts_ready"] == src_status["contexts_expected"],
    }
