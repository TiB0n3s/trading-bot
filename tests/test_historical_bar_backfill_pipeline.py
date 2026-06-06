#!/usr/bin/env python3
"""Tests for chunked multi-year Polygon historical bar backfill."""

from __future__ import annotations

import sys
from pathlib import Path
import tempfile
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pipeline.historical_bar_backfill as backfill_pipeline  # noqa: E402


class FakeArchiveService:
    calls = []

    def archive_polygon_1m_bars(self, **kwargs):
        FakeArchiveService.calls.append(kwargs)
        return SimpleNamespace(
            as_dict=lambda: {
                "symbol": kwargs["symbol"],
                "start_date": str(kwargs["start_date"]),
                "end_date": str(kwargs["end_date"]),
                "regular_hours_bars": 10,
                "cached_rows": 10 if not kwargs["dry_run"] else 0,
                "persisted_pattern_rows": 8 if not kwargs["dry_run"] else 0,
                "errors": [],
            }
        )


def test_historical_bar_backfill_chunks_date_range_and_symbols():
    original_service = backfill_pipeline.HistoricalBarArchiveService
    try:
        FakeArchiveService.calls = []
        backfill_pipeline.HistoricalBarArchiveService = lambda **kwargs: FakeArchiveService()
        code = backfill_pipeline.main(
            [
                "--start-date",
                "2026-01-01",
                "--end-date",
                "2026-02-10",
                "--symbol",
                "AAPL,MSFT",
                "--chunk-days",
                "30",
                "--dry-run",
            ]
        )
    finally:
        backfill_pipeline.HistoricalBarArchiveService = original_service

    assert code == 0
    assert len(FakeArchiveService.calls) == 4
    assert FakeArchiveService.calls[0]["symbol"] == "AAPL"
    assert str(FakeArchiveService.calls[0]["start_date"]) == "2026-01-01"
    assert str(FakeArchiveService.calls[0]["end_date"]) == "2026-01-30"
    assert str(FakeArchiveService.calls[1]["start_date"]) == "2026-01-31"
    assert str(FakeArchiveService.calls[1]["end_date"]) == "2026-02-10"
    assert FakeArchiveService.calls[0]["dry_run"] is True


def test_historical_bar_backfill_max_chunks_limits_smoke_runs():
    original_service = backfill_pipeline.HistoricalBarArchiveService
    try:
        FakeArchiveService.calls = []
        backfill_pipeline.HistoricalBarArchiveService = lambda **kwargs: FakeArchiveService()
        code = backfill_pipeline.main(
            [
                "--start-date",
                "2026-01-01",
                "--end-date",
                "2026-03-31",
                "--symbol",
                "AAPL,MSFT",
                "--chunk-days",
                "30",
                "--max-chunks",
                "1",
                "--dry-run",
            ]
        )
    finally:
        backfill_pipeline.HistoricalBarArchiveService = original_service

    assert code == 0
    assert len(FakeArchiveService.calls) == 1


def test_historical_bar_backfill_refuses_concurrent_lock():
    with tempfile.TemporaryDirectory() as tmp:
        lock_path = Path(tmp) / "historical.lock"
        lock_handle = backfill_pipeline._acquire_lock(lock_path)
        try:
            code = backfill_pipeline.main(
                [
                    "--start-date",
                    "2026-01-01",
                    "--end-date",
                    "2026-01-02",
                    "--symbol",
                    "AAPL",
                    "--dry-run",
                    "--lock-file",
                    str(lock_path),
                ]
            )
        finally:
            if lock_handle:
                lock_handle.close()

    assert code == 75


if __name__ == "__main__":
    test_historical_bar_backfill_chunks_date_range_and_symbols()
    print("[OK] test_historical_bar_backfill_chunks_date_range_and_symbols")
    test_historical_bar_backfill_max_chunks_limits_smoke_runs()
    print("[OK] test_historical_bar_backfill_max_chunks_limits_smoke_runs")
    test_historical_bar_backfill_refuses_concurrent_lock()
    print("[OK] test_historical_bar_backfill_refuses_concurrent_lock")
    print("\nAll 3 historical bar backfill pipeline tests passed.")
