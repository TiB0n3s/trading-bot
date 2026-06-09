#!/usr/bin/env python3
"""Tests for ML-supported candidate taken/skipped outcome reporting."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.ml_supported_buy_outcome_service import (  # noqa: E402
    MlSupportedBuyOutcomeService,
)


class FakeRepo:
    def auto_buy_candidate_rows(self, target_date):
        return [
            {
                "timestamp": f"{target_date} 10:00:00",
                "symbol": "AAPL",
                "decision": "strong_buy_candidate",
                "score": 20.0,
                "reason": "ml_supported",
                "hard_block_reason": "",
                "order_submitted": 1,
            },
            {
                "timestamp": f"{target_date} 10:05:00",
                "symbol": "MSFT",
                "decision": "watch",
                "score": 16.0,
                "reason": "ml_supported_but_blocked",
                "hard_block_reason": "macro_position_limit",
                "order_submitted": 0,
            },
            {
                "timestamp": f"{target_date} 10:10:00",
                "symbol": "NVDA",
                "decision": "skip",
                "score": 25.0,
                "reason": "not_supported",
                "hard_block_reason": "",
                "order_submitted": 0,
            },
        ]

    def feature_price_at_or_before(self, symbol, timestamp):
        return {"AAPL": (100.0, timestamp), "MSFT": (200.0, timestamp)}.get(symbol, (None, None))

    def feature_price_at_or_after(self, symbol, timestamp, minutes):
        prices = {
            ("AAPL", 15): (101.0, "later"),
            ("AAPL", 60): (102.0, "later"),
            ("MSFT", 15): (198.0, "later"),
            ("MSFT", 60): (196.0, "later"),
        }
        return prices.get((symbol, minutes), (None, None))


def test_ml_supported_buy_outcome_report_splits_taken_and_skipped():
    report = MlSupportedBuyOutcomeService(FakeRepo()).report("2026-06-09")

    assert report["rows"] == 2
    assert report["taken_rows"] == 1
    assert report["skipped_rows"] == 1
    assert report["by_status"]["taken"]["avg_return_15m_pct"] == 1.0
    assert report["by_status"]["taken"]["avg_return_60m_pct"] == 2.0
    assert report["by_status"]["skipped"]["avg_return_15m_pct"] == -1.0
    assert report["by_status"]["skipped"]["avg_return_60m_pct"] == -2.0
    assert [row["symbol"] for row in report["candidates"]] == ["AAPL", "MSFT"]


if __name__ == "__main__":
    test_ml_supported_buy_outcome_report_splits_taken_and_skipped()
    print("[OK] test_ml_supported_buy_outcome_report_splits_taken_and_skipped")
