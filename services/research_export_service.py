"""Offline research exports backed by Parquet and DuckDB."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import json
from pathlib import Path
from typing import Any

from repositories.research_export_repo import ResearchExportRepository


RESEARCH_EXPORT_VERSION = "research_export_v1"
RESEARCH_EXPORT_RUNTIME_EFFECT = "offline_research_only_no_live_authority"


@dataclass(frozen=True)
class ResearchDatasetSpec:
    name: str
    table: str
    date_columns: tuple[str, ...]


@dataclass(frozen=True)
class ResearchExportResult:
    ok: bool
    target_date: str
    output_dir: Path
    manifest_path: Path
    duckdb_path: Path | None
    datasets: list[dict[str, Any]]
    version: str = RESEARCH_EXPORT_VERSION
    runtime_effect: str = RESEARCH_EXPORT_RUNTIME_EFFECT


DEFAULT_RESEARCH_DATASETS: tuple[ResearchDatasetSpec, ...] = (
    ResearchDatasetSpec(
        "decision_snapshots",
        "decision_snapshots",
        ("decision_time", "created_at", "timestamp"),
    ),
    ResearchDatasetSpec("trades", "trades", ("timestamp", "created_at")),
    ResearchDatasetSpec(
        "matched_trades",
        "matched_trades",
        ("entry_timestamp", "exit_timestamp", "created_at"),
    ),
    ResearchDatasetSpec(
        "exit_snapshots",
        "exit_snapshots",
        ("exit_timestamp", "created_at"),
    ),
    ResearchDatasetSpec(
        "rejected_signal_outcomes",
        "rejected_signal_outcomes",
        ("timestamp", "generated_at", "decision_time", "created_at", "outcome_timestamp"),
    ),
    ResearchDatasetSpec(
        "candidate_universe",
        "candidate_universe",
        ("candidate_ts", "created_at"),
    ),
    ResearchDatasetSpec(
        "auto_buy_candidates",
        "auto_buy_candidates",
        ("timestamp", "created_at"),
    ),
)


def _import_pyarrow():
    try:
        import pyarrow as pa
        import pyarrow.parquet as pq
    except Exception as exc:  # pragma: no cover - exercised by operator env
        raise RuntimeError(
            "PyArrow is required for research export. Install pyarrow in the venv."
        ) from exc
    return pa, pq


def _import_duckdb():
    try:
        import duckdb
    except Exception as exc:  # pragma: no cover - exercised by operator env
        raise RuntimeError(
            "DuckDB is required for research export. Install duckdb in the venv."
        ) from exc
    return duckdb


class ResearchExportService:
    def __init__(
        self,
        repository: ResearchExportRepository,
        *,
        output_root: Path | str,
        datasets: tuple[ResearchDatasetSpec, ...] = DEFAULT_RESEARCH_DATASETS,
    ):
        self.repository = repository
        self.output_root = Path(output_root)
        self.datasets = datasets

    @staticmethod
    def _write_parquet(rows: list[dict[str, Any]], path: Path) -> None:
        pa, pq = _import_pyarrow()
        table = pa.Table.from_pylist(rows)
        pq.write_table(table, path)

    @staticmethod
    def _create_duckdb_views(duckdb_path: Path, dataset_entries: list[dict[str, Any]]) -> None:
        duckdb = _import_duckdb()
        con = duckdb.connect(str(duckdb_path))
        try:
            for entry in dataset_entries:
                parquet_path = entry.get("parquet_path")
                if not parquet_path:
                    continue
                name = entry["name"]
                parquet_literal = str(parquet_path).replace("'", "''")
                con.execute(
                    f"CREATE OR REPLACE VIEW {name} AS "
                    f"SELECT * FROM read_parquet('{parquet_literal}')"
                )
        finally:
            con.close()

    def export_daily(
        self,
        target_date: str,
        *,
        limit: int | None = None,
    ) -> ResearchExportResult:
        output_dir = self.output_root / target_date
        output_dir.mkdir(parents=True, exist_ok=True)

        dataset_entries: list[dict[str, Any]] = []
        for spec in self.datasets:
            rows, date_columns = self.repository.rows_for_date(
                table=spec.table,
                target_date=target_date,
                date_columns=spec.date_columns,
                limit=limit,
            )
            entry: dict[str, Any] = {
                "name": spec.name,
                "table": spec.table,
                "rows": len(rows),
                "date_columns": date_columns,
                "parquet_path": None,
                "status": "empty" if not rows else "exported",
            }
            if rows:
                parquet_path = output_dir / f"{spec.name}.parquet"
                self._write_parquet(rows, parquet_path)
                entry["parquet_path"] = str(parquet_path)
            dataset_entries.append(entry)

        duckdb_path = output_dir / "research.duckdb"
        exported_entries = [entry for entry in dataset_entries if entry.get("parquet_path")]
        if exported_entries:
            self._create_duckdb_views(duckdb_path, exported_entries)
        else:
            duckdb_path = None

        manifest = {
            "version": RESEARCH_EXPORT_VERSION,
            "runtime_effect": RESEARCH_EXPORT_RUNTIME_EFFECT,
            "target_date": target_date,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "output_dir": str(output_dir),
            "duckdb_path": str(duckdb_path) if duckdb_path else None,
            "datasets": dataset_entries,
        }
        manifest_path = output_dir / "manifest.json"
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

        return ResearchExportResult(
            ok=bool(exported_entries),
            target_date=target_date,
            output_dir=output_dir,
            manifest_path=manifest_path,
            duckdb_path=duckdb_path,
            datasets=dataset_entries,
        )
