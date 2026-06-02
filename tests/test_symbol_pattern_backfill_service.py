#!/usr/bin/env python3
"""Tests for read-time symbol pattern compatibility/backfill."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.symbol_pattern_backfill_service import canonical_symbol_pattern_state


def test_prefers_native_pattern_state():
    pattern = canonical_symbol_pattern_state(
        {
            "pattern_state": {
                "pattern_label": "native_pattern",
                "directional_bias": "constructive",
            }
        }
    )

    assert pattern["pattern_label"] == "native_pattern"
    assert pattern["directional_bias"] == "constructive"
    assert pattern["source"] == "canonical_pattern_state"
    assert pattern["authority"] == "observe_only_no_live_authority"


def test_reads_historical_analytics_pattern():
    pattern = canonical_symbol_pattern_state(
        {
            "analytics_state": {
                "ai_momentum_pattern": {
                    "pattern_label": "historical_pattern",
                    "directional_bias": "risk_negative",
                    "runtime_effect": "observe_only_no_live_authority",
                    "prediction_layer": {"status": "observe_only"},
                }
            }
        }
    )

    assert pattern["pattern_label"] == "historical_pattern"
    assert pattern["directional_bias"] == "risk_negative"
    assert pattern["prediction_status"] == "observe_only"
    assert pattern["source"] == "analytics_state_ai_momentum_pattern"


def test_derives_pattern_from_canonical_sections_when_missing():
    pattern = canonical_symbol_pattern_state(
        {
            "regime_state": {
                "participation_state": "confirmed",
                "vwap_state": "above_vwap",
            },
            "momentum_state": {
                "state": "accelerating",
                "session_label": "strong_uptrend",
                "volume_state": "surge",
            },
            "trend_state": {
                "direction": "bullish",
                "strength": "confirmed",
            },
        }
    )

    assert pattern["pattern_label"] == "trend_continuation_with_participation"
    assert pattern["directional_bias"] == "constructive"
    assert pattern["source"] == "derived_from_canonical_sections"
    assert pattern["authority"] == "observe_only_no_live_authority"


def main():
    tests = [
        test_prefers_native_pattern_state,
        test_reads_historical_analytics_pattern,
        test_derives_pattern_from_canonical_sections_when_missing,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} symbol pattern backfill tests passed.")


if __name__ == "__main__":
    main()
