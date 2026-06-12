#!/usr/bin/env python3
"""Feature jobs should no-op outside regular market hours."""

from __future__ import annotations

import sys
from datetime import datetime
from pathlib import Path

import pytz

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

import scripts.label_v1_builder as label_v1_builder  # noqa: E402
import scripts.live_features as live_features  # noqa: E402

ET = pytz.timezone("America/New_York")


def _assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_live_features_noops_outside_regular_market_hours():
    original_argv = sys.argv[:]
    original_now_et = live_features.now_et
    original_is_trading_day = live_features.is_trading_day
    original_is_market_hours = live_features.is_market_hours
    original_collect_all_symbols = live_features.collect_all_symbols
    try:
        sys.argv = ["live_features.py", "--all-symbols", "--write"]
        live_features.now_et = lambda: ET.localize(datetime(2026, 6, 12, 9, 0))
        live_features.is_trading_day = lambda date_value: True
        live_features.is_market_hours = lambda now: False

        def _fail_collect(*args, **kwargs):
            raise AssertionError("live feature collection should not run outside market hours")

        live_features.collect_all_symbols = _fail_collect
        _assert_equal(live_features.main(), 0, "live feature outside-hours exit")
    finally:
        sys.argv = original_argv
        live_features.now_et = original_now_et
        live_features.is_trading_day = original_is_trading_day
        live_features.is_market_hours = original_is_market_hours
        live_features.collect_all_symbols = original_collect_all_symbols


def test_label_v1_builder_noops_outside_regular_market_hours():
    original_now_et = label_v1_builder.now_et
    original_is_market_hours = label_v1_builder.is_market_hours
    original_validate = label_v1_builder.validate_feature_snapshot_contract
    try:
        label_v1_builder.now_et = lambda: ET.localize(datetime(2026, 6, 12, 9, 0))
        label_v1_builder.is_market_hours = lambda now: False

        def _fail_validate(*args, **kwargs):
            raise AssertionError("label builder should not touch DB outside market hours")

        label_v1_builder.validate_feature_snapshot_contract = _fail_validate
        result = label_v1_builder.build_labels()
        _assert_equal(result["status"], "skipped", "label builder status")
        _assert_equal(result["reason"], "outside_regular_market_hours", "label builder reason")
        _assert_equal(result["ok"], True, "label builder ok")
    finally:
        label_v1_builder.now_et = original_now_et
        label_v1_builder.is_market_hours = original_is_market_hours
        label_v1_builder.validate_feature_snapshot_contract = original_validate


def main():
    tests = [
        test_live_features_noops_outside_regular_market_hours,
        test_label_v1_builder_noops_outside_regular_market_hours,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} feature job market-hours guard tests passed.")


if __name__ == "__main__":
    main()
