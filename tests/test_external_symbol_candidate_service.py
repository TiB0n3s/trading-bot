#!/usr/bin/env python3
"""Tests for external-symbol research candidate state."""

from __future__ import annotations

import sqlite3
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.external_symbol_candidate_service import (  # noqa: E402
    STATUS_BACKFILL_PENDING,
    STATUS_CONTEXT_ONLY,
    STATUS_READY_REVIEW,
    ExternalSymbolCandidateService,
)


def _write_bar_rows(db_path: Path, symbol: str, *, days: int, rows_per_day: int = 10) -> None:
    with sqlite3.connect(db_path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS bar_pattern_features (
                symbol TEXT,
                bar_timestamp TEXT,
                timeframe TEXT
            )
            """
        )
        for day in range(1, days + 1):
            for minute in range(rows_per_day):
                con.execute(
                    """
                    INSERT INTO bar_pattern_features (symbol, bar_timestamp, timeframe)
                    VALUES (?, ?, '1m')
                    """,
                    (symbol, f"2026-06-{day:02d}T09:{minute:02d}:00Z"),
                )


def test_external_candidate_refresh_marks_unknown_for_backfill_then_review_ready():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        db_path = base / "trades.db"
        state_path = base / "state.json"
        service = ExternalSymbolCandidateService(state_path=state_path, db_path=db_path)
        discovery = {
            "start_date": "2026-06-01",
            "end_date": "2026-06-05",
            "findings": [
                {
                    "symbol": "XYZ",
                    "symbol_class": "unknown_external",
                    "mentions": 3,
                    "trusted_mentions": 2,
                    "linked_approved_symbols": ["AAPL", "MSFT"],
                }
            ],
        }

        result = service.refresh_from_discovery(
            discovery,
            min_mentions=2,
            min_trusted_mentions=1,
            min_bar_rows=20,
            min_bar_days=2,
        )
        assert result.backfill_symbols == ["XYZ"]
        assert result.candidates[0]["status"] == STATUS_BACKFILL_PENDING

        _write_bar_rows(db_path, "XYZ", days=3, rows_per_day=10)
        result = service.refresh_from_discovery(
            discovery,
            min_mentions=2,
            min_trusted_mentions=1,
            min_bar_rows=20,
            min_bar_days=2,
        )
        assert result.backfill_symbols == []
        assert result.candidates[0]["status"] == STATUS_READY_REVIEW


def test_external_candidate_refresh_keeps_context_only_non_authoritative():
    with tempfile.TemporaryDirectory() as tmp:
        service = ExternalSymbolCandidateService(
            state_path=Path(tmp) / "state.json",
            db_path=Path(tmp) / "trades.db",
        )
        result = service.refresh_from_discovery(
            {
                "start_date": "2026-06-01",
                "end_date": "2026-06-05",
                "findings": [
                    {
                        "symbol": "ARM",
                        "symbol_class": "context_only",
                        "mentions": 5,
                        "trusted_mentions": 3,
                        "linked_approved_symbols": ["AAPL", "NVDA"],
                    }
                ],
            }
        )
        assert result.candidates[0]["status"] == STATUS_CONTEXT_ONLY
        assert result.backfill_symbols == []


def main():
    test_external_candidate_refresh_marks_unknown_for_backfill_then_review_ready()
    test_external_candidate_refresh_keeps_context_only_non_authoritative()
    print("external symbol candidate service tests passed")


if __name__ == "__main__":
    main()
