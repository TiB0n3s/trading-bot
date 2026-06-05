#!/usr/bin/env python3
"""Tests for Polygon tick-level trade archive pipeline."""

from __future__ import annotations

import csv
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline.polygon_tick_archive import archive_polygon_trades  # noqa: E402


class _FakePolygon:
    def trade_dicts(self, symbol, *, timestamp, limit=50000, **kwargs):
        assert symbol == "AAPL"
        assert str(timestamp) == "2026-06-02"
        assert limit == 2
        return [
            {
                "timestamp": "2026-06-02T13:30:00+00:00",
                "price": 100.25,
                "size": 50,
                "exchange": 11,
                "conditions": [12],
                "sequence_number": 123,
                "tape": 3,
            }
        ]


def test_archive_polygon_trades_writes_csv_when_available():
    with tempfile.TemporaryDirectory() as tmp:
        cache_dir = Path(tmp) / "ticks"
        result = archive_polygon_trades(
            symbol="aapl",
            target_date="2026-06-02",
            cache_dir=cache_dir,
            limit=2,
            polygon_market_data=_FakePolygon(),
        )
        with Path(result.cache_path).open(newline="", encoding="utf-8") as fh:
            rows = list(csv.DictReader(fh))

    assert result.report_version == "polygon_tick_archive_v1"
    assert result.runtime_effect == "offline_tick_archive_no_live_authority"
    assert result.trades == 1
    assert rows[0]["price"] == "100.25"
    assert rows[0]["conditions"] == "[12]"


if __name__ == "__main__":
    test_archive_polygon_trades_writes_csv_when_available()
    print("[OK] test_archive_polygon_trades_writes_csv_when_available")
    print("\nAll 1 Polygon tick archive pipeline tests passed.")
