#!/usr/bin/env python3
"""Tests for post-trade learning summaries."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.post_trade_learning_service import build_post_trade_learning_payload


def test_post_trade_learning_summarizes_expectancy_and_gate_value():
    payload = build_post_trade_learning_payload(
        [
            {
                "symbol": "AAPL",
                "approved": 1,
                "realized_return_pct": 0.6,
                "setup_label": "clean_breakout",
                "market_regime": "trend_expansion",
            },
            {
                "symbol": "MSFT",
                "approved": 1,
                "realized_return_pct": -0.3,
                "setup_label": "messy_breakout",
                "market_regime": "compression_chop",
            },
            {
                "symbol": "META",
                "approved": 0,
                "rejection_reason": "prediction_gate",
                "rejected_return_60m": -0.4,
                "setup_label": "messy_breakout",
                "market_regime": "compression_chop",
            },
            {
                "symbol": "NVDA",
                "approved": 0,
                "rejection_reason": "trend_confirmation",
                "rejected_return_60m": 0.5,
                "setup_label": "clean_breakout",
                "market_regime": "trend_expansion",
            },
        ]
    )

    assert payload.summary["rows"] == 4
    assert payload.summary["approved_with_outcomes"] == 2
    assert payload.summary["rejected_with_outcomes"] == 2
    setup_rows = payload.expectancy_by_dimension["setup_label"]
    clean = [row for row in setup_rows if row["bucket"] == "clean_breakout"][0]
    assert clean["count"] == 2
    assert clean["avg_return_pct"] == 0.55
    prediction_gate = [
        row for row in payload.gate_value if row["gate"] == "prediction_gate"
    ][0]
    assert prediction_gate["would_have_helped"] == 1
    assert prediction_gate["help_rate"] == 1.0


def main():
    tests = [test_post_trade_learning_summarizes_expectancy_and_gate_value]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} post-trade learning service tests passed.")


if __name__ == "__main__":
    main()
