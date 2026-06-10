"""Operator command for offline DuckDB/PyArrow research exports."""

from __future__ import annotations

from pathlib import Path

from repositories.research_export_repo import ResearchExportRepository
from services.research_export_service import (
    RESEARCH_EXPORT_RUNTIME_EFFECT,
    RESEARCH_EXPORT_VERSION,
    ResearchExportService,
)


def run_research_export(
    target_date: str,
    *,
    base_dir: Path,
    limit: int | None = None,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Research Export — {target_date}")
    print("=" * 72)
    print(f"version                : {RESEARCH_EXPORT_VERSION}")
    print(f"runtime_effect         : {RESEARCH_EXPORT_RUNTIME_EFFECT}")

    service = ResearchExportService(
        ResearchExportRepository(base_dir / "trades.db"),
        output_root=base_dir / "research_exports",
    )
    try:
        result = service.export_daily(target_date, limit=limit)
    except RuntimeError as exc:
        print(f"[FAIL] {exc}")
        return False

    print(f"output_dir             : {result.output_dir}")
    print(f"manifest               : {result.manifest_path}")
    print(f"duckdb                 : {result.duckdb_path or '-'}")
    print()
    print(f"{'dataset':<28} {'rows':>8} {'status':<10} date_columns")
    print("-" * 72)
    for dataset in result.datasets:
        date_columns = ",".join(dataset.get("date_columns") or []) or "-"
        print(f"{dataset['name']:<28} {dataset['rows']:>8} {dataset['status']:<10} {date_columns}")

    if not result.ok:
        print("[WARN] no daily research rows were exported")
        return False
    print("[OK] research export complete")
    return True
