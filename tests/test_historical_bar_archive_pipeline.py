#!/usr/bin/env python3
"""Tests for the historical bar archive pipeline wrapper."""

from __future__ import annotations

import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pipeline.historical_bar_archive as archive_pipeline  # noqa: E402


class FakeArchiveService:
    calls = []

    def __init__(self, cache_dir=None):
        self.cache_dir = cache_dir

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
    assert FakeArchiveService.calls[0]["dry_run"] is True


if __name__ == "__main__":
    test_historical_archive_pipeline_loops_symbols_and_reports_rows()
    print("[OK] test_historical_archive_pipeline_loops_symbols_and_reports_rows")
    print("\nAll 1 historical archive pipeline tests passed.")
