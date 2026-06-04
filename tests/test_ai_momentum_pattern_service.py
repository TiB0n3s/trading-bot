#!/usr/bin/env python3
"""Tests for observe-only AI momentum/trend pattern interpretation."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.ai_momentum_pattern_service import (  # noqa: E402
    AI_MOMENTUM_PATTERN_AUTHORITY,
    AIMomentumPatternConfig,
    AIMomentumPatternService,
    deterministic_momentum_pattern,
)


def test_deterministic_pattern_detects_constructive_continuation():
    result = deterministic_momentum_pattern(
        symbol="NVDA",
        action="buy",
        regime_state={
            "session_phase": "first_30m",
            "breakout_quality": "confirmed_expansion_breakout",
            "vwap_state": "above_vwap",
            "participation_state": "confirmed",
        },
        momentum_state={
            "state": "accelerating",
            "session_label": "strong_uptrend",
            "volume_state": "surge",
        },
        trend_state={"direction": "bullish", "strength": "confirmed"},
    )

    assert result["pattern_label"] == "trend_continuation_with_participation"
    assert result["directional_bias"] == "constructive"
    assert result["expected_horizon"] == "15m_to_60m"
    assert result["favorable_move_probability"] == 0.56
    assert result["expected_mfe_pct"] == 0.85
    assert result["expected_mae_pct"] == -0.45
    assert result["historical_bucket"]["status"] == "needs_lifecycle_outcomes"
    assert result["prediction_layer"]["status"] == "observe_only"
    assert result["prediction_layer"]["promotion_status"] == "not_ready"
    assert result["authority"] == AI_MOMENTUM_PATTERN_AUTHORITY
    assert result["runtime_effect"] == "observe_only_no_live_authority"


def test_deterministic_pattern_flags_deterioration():
    result = deterministic_momentum_pattern(
        symbol="NVDA",
        action="buy",
        regime_state={"vwap_state": "lost_vwap"},
        momentum_state={"state": "decelerating", "session_label": "fading"},
        trend_state={"direction": "bullish", "strength": "confirmed"},
    )

    assert result["pattern_label"] == "momentum_deterioration"
    assert result["directional_bias"] == "risk_negative"
    assert result["favorable_move_probability"] == 0.38
    assert result["confidence_quality"] == "directional_risk_prior"
    assert result["authority"] == AI_MOMENTUM_PATTERN_AUTHORITY


def test_deterministic_pattern_reads_constructive_candle_physics():
    result = deterministic_momentum_pattern(
        symbol="AAPL",
        action="buy",
        regime_state={"vwap_state": "above_vwap", "participation_state": "confirmed"},
        momentum_state={"state": "mixed", "session_label": "rangebound", "volume_state": "normal"},
        trend_state={"direction": "neutral", "strength": "unknown"},
        candle_state={
            "candle_body_pct": 0.62,
            "close_location": 0.88,
            "range_atr_ratio": 1.3,
            "volume_weighted_pressure_3": 0.4,
            "triple_barrier_label": 1,
        },
    )

    assert result["pattern_label"] == "constructive_candle_pressure"
    assert result["directional_bias"] == "constructive"
    assert any("candle=" in item for item in result["rationale"])
    assert "candle_physics" not in result["missing_evidence"]
    assert result["authority"] == AI_MOMENTUM_PATTERN_AUTHORITY


def test_deterministic_pattern_reads_bearish_candle_physics():
    result = deterministic_momentum_pattern(
        symbol="AAPL",
        action="buy",
        regime_state={"vwap_state": "above_vwap", "participation_state": "confirmed"},
        momentum_state={"state": "mixed", "session_label": "rangebound", "volume_state": "normal"},
        trend_state={"direction": "bullish", "strength": "confirmed"},
        candle_state={
            "candle_body_pct": 0.50,
            "close_location": 0.12,
            "range_atr_ratio": 1.8,
            "volume_weighted_pressure_3": -0.6,
            "triple_barrier_label": -1,
        },
    )

    assert result["pattern_label"] == "bearish_candle_pressure"
    assert result["directional_bias"] == "risk_negative"
    assert result["favorable_move_probability"] == 0.37


def test_provider_output_is_sanitized_to_observe_only():
    def provider(_prompt):
        return {
            "pattern_label": "provider_pattern",
            "directional_bias": "constructive",
            "continuation_assessment": "strong",
            "failure_mode": "none",
            "confidence": "high",
            "expected_horizon": "15m_to_60m",
            "favorable_move_probability": 0.91,
            "expected_mfe_pct": 2.1,
            "expected_mae_pct": -0.4,
            "prediction_layer": {"status": "block"},
            "missing_evidence": [],
            "rationale": ["provider rationale"],
            "authority": "approve_buy",
        }

    service = AIMomentumPatternService(
        config=AIMomentumPatternConfig(enabled=True, provider_name="test_provider"),
        provider=provider,
    )
    result = service.interpret(
        symbol="NVDA",
        action="buy",
        regime_state={},
        momentum_state={},
        trend_state={},
    )

    assert result["provider"] == "test_provider"
    assert result["pattern_label"] == "provider_pattern"
    assert result["favorable_move_probability"] == 0.91
    assert result["expected_mfe_pct"] == 2.1
    assert result["prediction_layer"]["status"] == "observe_only"
    assert result["authority"] == AI_MOMENTUM_PATTERN_AUTHORITY
    assert result["runtime_effect"] == "observe_only_no_live_authority"
    assert "ai_pattern_observe_only" in result["rationale"]


def test_provider_error_falls_back_safely():
    def provider(_prompt):
        raise RuntimeError("model unavailable")

    service = AIMomentumPatternService(
        config=AIMomentumPatternConfig(enabled=True, provider_name="test_provider"),
        provider=provider,
    )
    result = service.interpret(
        symbol="NVDA",
        action="buy",
        regime_state={},
        momentum_state={},
        trend_state={},
    )

    assert result["provider"] == "test_provider_error_fallback"
    assert result["authority"] == AI_MOMENTUM_PATTERN_AUTHORITY
    assert "provider_error" in result


def main():
    tests = [
        test_deterministic_pattern_detects_constructive_continuation,
        test_deterministic_pattern_flags_deterioration,
        test_deterministic_pattern_reads_constructive_candle_physics,
        test_deterministic_pattern_reads_bearish_candle_physics,
        test_provider_output_is_sanitized_to_observe_only,
        test_provider_error_falls_back_safely,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} AI momentum pattern service tests passed.")


if __name__ == "__main__":
    main()
