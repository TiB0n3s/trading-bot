#!/usr/bin/env python3
"""Tests for Polygon historical bar archive and pattern backfill."""

from __future__ import annotations

import csv
import io
import sys
import tempfile
from contextlib import redirect_stdout
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.historical_bar_archive_service import HistoricalBarArchiveService  # noqa: E402
from services.ops_checks.historical_bar_archive_checks import run_historical_bar_archive  # noqa: E402


class _FakePolygon:
    configured = True

    def __init__(self):
        self.calls = []

    def aggregate_bar_dicts(self, symbol, **kwargs):
        self.calls.append((symbol, kwargs))
        start = datetime(2026, 6, 2, 13, 30, tzinfo=timezone.utc)
        rows = []
        close = 100.0
        for idx in range(35):
            close += 0.08 if idx < 20 else 0.18
            rows.append(
                {
                    "timestamp": (start + timedelta(minutes=idx)).isoformat(),
                    "open": close - 0.04,
                    "high": close + 0.14,
                    "low": close - 0.10,
                    "close": round(close, 4),
                    "volume": 1000 + idx * 25,
                    "vwap": round(close - 0.01, 4),
                }
            )
        rows.append(
            {
                "timestamp": datetime(2026, 6, 2, 21, 0, tzinfo=timezone.utc).isoformat(),
                "open": 105,
                "high": 106,
                "low": 104,
                "close": 105,
                "volume": 100,
                "vwap": 105,
            }
        )
        return rows


def test_historical_bar_archive_filters_rth_caches_csv_and_builds_patterns(tmp_path: Path):
    fake = _FakePolygon()
    service = HistoricalBarArchiveService(polygon_market_data=fake)
    result = service.archive_polygon_1m_bars(
        symbol="aapl",
        start_date="2026-06-02",
        end_date="2026-06-02",
        cache_dir=tmp_path / "bars",
        db_path=tmp_path / "trades.db",
        build_patterns=True,
        horizon_bars=10,
    )

    assert result.symbol == "AAPL"
    assert result.trading_days_requested == 1
    assert result.raw_bars == 36
    assert result.regular_hours_bars == 35
    assert result.cached_rows == 35
    assert result.pattern_rows > 0
    assert result.persisted_pattern_rows == result.pattern_rows
    assert len(fake.calls) == 1
    assert fake.calls[0][1]["from_date"] == "2026-06-02"
    assert fake.calls[0][1]["to_date"] == "2026-06-02"
    assert fake.calls[0][1]["adjusted"] is True

    with Path(result.cache_path).open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    assert len(rows) == 35
    assert rows[0]["Timestamp"].endswith("-04:00")
    assert rows[0]["IntervalStart"] == rows[0]["Timestamp"]
    assert rows[0]["IntervalSemantics"] == "inclusive_start_regular_hours_1m"
    assert rows[0]["Source"] == "polygon_aggregate_1m"
    assert rows[0]["Adjusted"] == "True"
    assert rows[0]["VWAP"]


def test_historical_bar_archive_ops_report_uses_fake_polygon(tmp_path: Path):
    buf = io.StringIO()
    with redirect_stdout(buf):
        ok = run_historical_bar_archive(
            "2026-06-02",
            base_dir=tmp_path,
            symbol="AAPL",
            end_date="2026-06-02",
            cache_dir=tmp_path / "bars",
            polygon_market_data=_FakePolygon(),
        )

    out = buf.getvalue()
    assert ok is True
    assert "Polygon Historical 1m Archive" in out
    assert "regular_hours_bars      : 35" in out
    assert "pattern_rows" in out
    assert "observe_only_pattern_learning_no_live_authority" in out


def main():
    with tempfile.TemporaryDirectory() as tmp:
        test_historical_bar_archive_filters_rth_caches_csv_and_builds_patterns(Path(tmp))
        print("[OK] test_historical_bar_archive_filters_rth_caches_csv_and_builds_patterns")

    with tempfile.TemporaryDirectory() as tmp:
        test_historical_bar_archive_ops_report_uses_fake_polygon(Path(tmp))
        print("[OK] test_historical_bar_archive_ops_report_uses_fake_polygon")

    print("\nAll 2 historical bar archive tests passed.")


if __name__ == "__main__":
    main()
