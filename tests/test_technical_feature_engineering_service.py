#!/usr/bin/env python3
"""Tests for dependency-light technical feature generation."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.technical_feature_engineering_service import build_technical_feature_set


def test_build_technical_feature_set_calculates_indicators_and_target():
    closes = [100 + i * 0.5 for i in range(30)]
    features = build_technical_feature_set(closes=closes, next_close=116).to_dict()

    assert features["available"] is True
    assert features["rsi_14"] == 100.0
    assert features["sma_5"] is not None
    assert features["macd"] is not None
    assert features["bollinger_position_20"] is not None
    assert features["target_next_close_up"] == 1
    assert "rsi_14" in features["feature_columns"]


def test_build_technical_feature_set_requires_enough_history():
    features = build_technical_feature_set(closes=[1, 2, 3]).to_dict()

    assert features["available"] is False
    assert "insufficient closes" in features["reason"]


def main():
    tests = [
        test_build_technical_feature_set_calculates_indicators_and_target,
        test_build_technical_feature_set_requires_enough_history,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} technical feature engineering tests passed.")


if __name__ == "__main__":
    main()
