#!/usr/bin/env python3
"""Tests for historical bar backfill cache helpers."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.historical_bar_backfill import _cache_file_has_rows  # noqa: E402


def test_cache_file_has_rows_rejects_header_only_cache():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "AAPL_1min_rth_2026-01-01_2026-01-03.csv"
        path.write_text("Timestamp,Open,High,Low,Close,Volume\n", encoding="utf-8")
        assert _cache_file_has_rows(path) is False
        path.write_text(
            "Timestamp,Open,High,Low,Close,Volume\n"
            "2026-01-01T14:30:00Z,1,2,1,2,100\n",
            encoding="utf-8",
        )
        assert _cache_file_has_rows(path) is True


if __name__ == "__main__":
    test_cache_file_has_rows_rejects_header_only_cache()
    print("[OK] test_cache_file_has_rows_rejects_header_only_cache")
