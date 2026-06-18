#!/usr/bin/env python3
"""Tests for offline research export service."""

from __future__ import annotations

import json
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories.research_export_repo import ResearchExportRepository
from services.research_export_service import (
    RESEARCH_EXPORT_RUNTIME_EFFECT,
    RESEARCH_EXPORT_VERSION,
    ResearchExportService,
)


def _dependencies_available() -> bool:
    try:
        import duckdb  # noqa: F401
        import pyarrow  # noqa: F401
    except Exception:
        return False
    return True


def test_research_export_writes_manifest_parquet_and_duckdb(tmp_path):
    if not _dependencies_available():
        print("skipping: duckdb/pyarrow unavailable")
        return

    tmp_path.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "trades.db"
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE decision_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_time TEXT,
                symbol TEXT,
                action TEXT,
                approved INTEGER,
                canonical_intelligence_hash TEXT
            )
            """
        )
        con.execute(
            """
            INSERT INTO decision_snapshots (
                decision_time, symbol, action, approved, canonical_intelligence_hash
            )
            VALUES (?, ?, ?, ?, ?)
            """,
            ("2026-06-02T10:00:00+00:00", "AAPL", "buy", 1, "hash-1"),
        )
        con.execute(
            """
            CREATE TABLE candidate_universe (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                candidate_ts TEXT,
                symbol TEXT,
                candidate_kind TEXT,
                candidate_status TEXT
            )
            """
        )
        con.execute(
            """
            INSERT INTO candidate_universe (
                candidate_ts, symbol, candidate_kind, candidate_status
            )
            VALUES (?, ?, ?, ?)
            """,
            (
                "2026-06-02T10:05:00+00:00",
                "MSFT",
                "entry_candidate",
                "near_threshold",
            ),
        )

    service = ResearchExportService(
        ResearchExportRepository(db_path),
        output_root=tmp_path / "exports",
        chunk_size=1,
    )
    result = service.export_daily("2026-06-02")

    assert result.ok is True
    assert result.manifest_path.exists()
    assert result.duckdb_path is not None
    assert result.duckdb_path.exists()

    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["version"] == RESEARCH_EXPORT_VERSION
    assert manifest["runtime_effect"] == RESEARCH_EXPORT_RUNTIME_EFFECT
    exported = {row["name"]: row for row in manifest["datasets"]}
    assert exported["decision_snapshots"]["rows"] == 1
    assert exported["decision_snapshots"]["chunk_size"] == 1
    assert exported["candidate_universe"]["rows"] == 1
    assert Path(exported["decision_snapshots"]["parquet_path"]).exists()


def test_research_export_empty_day_is_manifest_only(tmp_path):
    if not _dependencies_available():
        print("skipping: duckdb/pyarrow unavailable")
        return

    tmp_path.mkdir(parents=True, exist_ok=True)
    db_path = tmp_path / "trades.db"
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE decision_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                decision_time TEXT,
                symbol TEXT
            )
            """
        )

    service = ResearchExportService(
        ResearchExportRepository(db_path),
        output_root=tmp_path / "exports",
    )
    result = service.export_daily("2026-06-02")

    assert result.ok is False
    assert result.manifest_path.exists()
    assert result.duckdb_path is None
    manifest = json.loads(result.manifest_path.read_text())
    assert manifest["datasets"][0]["status"] == "empty"


if __name__ == "__main__":
    tests = [
        test_research_export_writes_manifest_parquet_and_duckdb,
        test_research_export_empty_day_is_manifest_only,
    ]
    with __import__("tempfile").TemporaryDirectory() as tmp:
        base = Path(tmp)
        for idx, test in enumerate(tests):
            test(base / f"case_{idx}")
    print(f"\nAll {len(tests)} research export tests passed.")
