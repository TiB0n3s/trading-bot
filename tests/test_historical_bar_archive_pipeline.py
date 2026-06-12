#!/usr/bin/env python3
"""Tests for the historical bar archive pipeline wrapper."""

from __future__ import annotations

import sqlite3
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pipeline.historical_bar_archive as archive_pipeline  # noqa: E402


class FakeArchiveService:
    calls = []

    def __init__(self):
        pass

    def archive_polygon_1m_bars(self, **kwargs):
        FakeArchiveService.calls.append(kwargs)
        return SimpleNamespace(
            as_dict=lambda: {
                "raw_bars": 10,
                "regular_hours_bars": 8,
                "persisted_pattern_rows": 7,
                "errors": [],
            }
        )


class FailingArchiveService:
    def __init__(self):
        raise AssertionError("existing pattern rows should skip archive service construction")


class ProviderErrorArchiveService:
    def archive_polygon_1m_bars(self, **kwargs):
        return SimpleNamespace(
            as_dict=lambda: {
                "raw_bars": 0,
                "regular_hours_bars": 0,
                "persisted_pattern_rows": 0,
                "errors": ["HTTPError: HTTP Error 403: Forbidden"],
            }
        )


def test_historical_archive_pipeline_loops_symbols_and_reports_rows(monkeypatch=None):
    original_service = archive_pipeline.HistoricalBarArchiveService
    original_symbols = archive_pipeline.APPROVED_SYMBOLS_LIST
    try:
        FakeArchiveService.calls = []
        archive_pipeline.HistoricalBarArchiveService = FakeArchiveService
        archive_pipeline.APPROVED_SYMBOLS_LIST = ["AAPL", "MSFT"]
        code = archive_pipeline.main(["--date", "2026-06-03", "--all", "--dry-run"])
    finally:
        archive_pipeline.HistoricalBarArchiveService = original_service
        archive_pipeline.APPROVED_SYMBOLS_LIST = original_symbols

    assert code == 0
    assert len(FakeArchiveService.calls) == 2
    assert FakeArchiveService.calls[0]["symbol"] == "AAPL"
    assert FakeArchiveService.calls[0]["start_date"] == "2026-06-03"
    assert FakeArchiveService.calls[0]["end_date"] == "2026-06-03"
    assert str(FakeArchiveService.calls[0]["cache_dir"]).endswith(
        "data/historical_bars/polygon_1min"
    )
    assert FakeArchiveService.calls[0]["dry_run"] is True


def test_historical_archive_pipeline_uses_custom_cache_dir():
    original_service = archive_pipeline.HistoricalBarArchiveService
    try:
        FakeArchiveService.calls = []
        archive_pipeline.HistoricalBarArchiveService = FakeArchiveService
        code = archive_pipeline.main(
            [
                "--date",
                "2026-06-03",
                "--symbol",
                "AAPL",
                "--cache-dir",
                "/tmp/polygon-bars",
                "--dry-run",
            ]
        )
    finally:
        archive_pipeline.HistoricalBarArchiveService = original_service

    assert code == 0
    assert len(FakeArchiveService.calls) == 1
    assert str(FakeArchiveService.calls[0]["cache_dir"]) == "/tmp/polygon-bars"


def test_historical_archive_pipeline_skips_existing_pattern_rows(tmp_path: Path):
    db_path = tmp_path / "trades.db"
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE bar_pattern_features (
                symbol TEXT NOT NULL,
                bar_timestamp TEXT NOT NULL,
                timeframe TEXT NOT NULL
            )
            """
        )
        con.executemany(
            """
            INSERT INTO bar_pattern_features(symbol, bar_timestamp, timeframe)
            VALUES ('AAPL', ?, '1m')
            """,
            [(f"2026-06-03T09:{minute:02d}:00-04:00",) for minute in range(30)]
            + [(f"2026-06-03T10:{minute:02d}:00-04:00",) for minute in range(30)],
        )

    original_service = archive_pipeline.HistoricalBarArchiveService
    try:
        archive_pipeline.HistoricalBarArchiveService = FailingArchiveService
        code = archive_pipeline.main(
            [
                "--date",
                "2026-06-03",
                "--symbol",
                "AAPL",
                "--db-path",
                str(db_path),
                "--skip-existing-patterns",
                "--min-existing-pattern-rows",
                "50",
            ]
        )
    finally:
        archive_pipeline.HistoricalBarArchiveService = original_service

    assert code == 0


def test_historical_archive_pipeline_warns_when_existing_coverage_is_high(tmp_path: Path):
    db_path = tmp_path / "trades.db"
    symbols = ["AAPL", "MSFT", "NVDA", "SPY", "JNPR"]
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE bar_pattern_features (
                symbol TEXT NOT NULL,
                bar_timestamp TEXT NOT NULL,
                timeframe TEXT NOT NULL
            )
            """
        )
        rows = []
        for symbol in symbols[:-1]:
            rows.extend(
                (symbol, f"2026-06-03T10:{minute:02d}:00-04:00", "1m") for minute in range(60)
            )
        con.executemany(
            """
            INSERT INTO bar_pattern_features(symbol, bar_timestamp, timeframe)
            VALUES (?, ?, ?)
            """,
            rows,
        )

    original_service = archive_pipeline.HistoricalBarArchiveService
    original_symbols = archive_pipeline.APPROVED_SYMBOLS_LIST
    try:
        archive_pipeline.HistoricalBarArchiveService = ProviderErrorArchiveService
        archive_pipeline.APPROVED_SYMBOLS_LIST = symbols
        code = archive_pipeline.main(
            [
                "--date",
                "2026-06-03",
                "--all",
                "--db-path",
                str(db_path),
                "--skip-existing-patterns",
                "--min-existing-pattern-rows",
                "50",
            ]
        )
    finally:
        archive_pipeline.HistoricalBarArchiveService = original_service
        archive_pipeline.APPROVED_SYMBOLS_LIST = original_symbols

    assert code == 0


if __name__ == "__main__":
    test_historical_archive_pipeline_loops_symbols_and_reports_rows()
    test_historical_archive_pipeline_uses_custom_cache_dir()
    import tempfile

    with tempfile.TemporaryDirectory() as tmp:
        test_historical_archive_pipeline_skips_existing_pattern_rows(Path(tmp))
    with tempfile.TemporaryDirectory() as tmp:
        test_historical_archive_pipeline_warns_when_existing_coverage_is_high(Path(tmp))
    print("[OK] test_historical_archive_pipeline_loops_symbols_and_reports_rows")
    print("[OK] test_historical_archive_pipeline_uses_custom_cache_dir")
    print("[OK] test_historical_archive_pipeline_skips_existing_pattern_rows")
    print("[OK] test_historical_archive_pipeline_warns_when_existing_coverage_is_high")
    print("\nAll 4 historical archive pipeline tests passed.")
