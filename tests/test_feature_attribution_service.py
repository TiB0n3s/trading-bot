#!/usr/bin/env python3
"""Tests for canonical lifecycle feature attribution."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.feature_attribution_service import build_feature_attribution_payload


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy value")


def _canonical(
    *,
    regime="trend_expansion",
    execution="allow",
    portfolio="allow",
    breakout="confirmed_expansion_breakout",
    participation="confirmed",
    volatility="low",
    structure="high_quality_structure",
    downside="contained_downside",
    utility="trade_candidate",
    confidence="medium",
    pattern="trend_continuation_with_participation",
    spread="tight",
    setup="breakout",
    phase="first_30m",
):
    return json.dumps(
        {
            "regime_state": {
                "market_regime": regime,
                "execution_quality_decision": execution,
                "portfolio_decision": portfolio,
                "breakout_quality": breakout,
                "participation_state": participation,
                "volatility_chase_risk": volatility,
                "downside_state": downside,
                "session_phase": phase,
                "spread_bucket": spread,
            },
            "setup_state": {
                "label": setup,
                "structure_state": structure,
            },
            "pattern_state": {
                "pattern_label": pattern,
                "runtime_effect": "observe_only_no_live_authority",
                "authority": "observe_only_no_live_authority",
            },
            "advisory_authority_state": {
                "utility_estimate": {"utility_decision": utility},
                "calibrated_confidence": {"confidence_quality": confidence},
            },
        }
    )


def test_feature_attribution_summarizes_family_deltas_and_guardrails():
    rows = [
        {
            "approved": 1,
            "decision_time": "2026-05-30T10:00:00+00:00",
            "realized_return_pct": 1.0,
            "mfe_pct": 1.4,
            "max_adverse_excursion_pct": -0.2,
            "canonical_intelligence_json": _canonical(),
        },
        {
            "approved": 1,
            "decision_time": "2026-05-30T10:30:00+00:00",
            "realized_return_pct": 0.8,
            "mfe_pct": 1.0,
            "max_adverse_excursion_pct": -0.1,
            "canonical_intelligence_json": _canonical(setup="vwap_recovery"),
        },
        {
            "approved": 0,
            "decision_time": "2026-05-30T10:45:00+00:00",
            "rejected_return_60m": 0.4,
            "rejected_max_favorable_60m": 0.7,
            "rejected_max_adverse_60m": -0.2,
            "canonical_intelligence_json": _canonical(setup="vwap_recovery"),
        },
        {
            "approved": 0,
            "decision_time": "2026-05-30T11:00:00+00:00",
            "rejected_return_60m": 0.2,
            "rejected_max_favorable_60m": 0.4,
            "rejected_max_adverse_60m": -0.3,
            "canonical_intelligence_json": _canonical(setup="breakout"),
        },
        {
            "approved": 1,
            "decision_time": "2026-05-31T10:00:00+00:00",
            "realized_return_pct": -0.6,
            "mfe_pct": 0.2,
            "max_adverse_excursion_pct": -1.1,
            "canonical_intelligence_json": _canonical(
                regime="compression_chop",
                execution="size_down",
                portfolio="size_down",
                breakout="liquidity_vacuum_breakout",
                participation="isolated_or_weak",
                volatility="high",
                structure="messy_range",
                downside="asymmetric_downside_high",
                utility="do_not_trade",
                confidence="low",
                pattern="momentum_deterioration",
                spread="wide",
                setup="late_chase",
                phase="midday",
            ),
        },
        {
            "approved": 0,
            "decision_time": "2026-05-31T11:00:00+00:00",
            "rejected_return_60m": -0.4,
            "rejected_max_favorable_60m": 0.1,
            "rejected_max_adverse_60m": -0.9,
            "canonical_intelligence_json": _canonical(
                regime="compression_chop",
                execution="size_down",
                portfolio="size_down",
                breakout="liquidity_vacuum_breakout",
                participation="isolated_or_weak",
                volatility="high",
                structure="messy_range",
                downside="asymmetric_downside_high",
                utility="do_not_trade",
                confidence="low",
                pattern="momentum_deterioration",
                spread="wide",
                setup="late_chase",
                phase="midday",
            ),
        },
    ]

    payload = build_feature_attribution_payload(
        rows,
        min_sample_size=2,
        rolling_window_size=2,
    )

    assert_equal(payload.summary["rows_with_outcome"], 6, "outcome rows")
    assert_equal(payload.summary["report_version"], "feature_attribution_v1", "version")
    assert_equal(payload.summary["authority_note"], "diagnostic_only_no_live_authority", "note")
    assert_equal(payload.summary["rolling_window_size"], 2, "rolling window size")
    regime = next(item for item in payload.families if item["family"] == "market_regime")
    assert_equal(regime["best_bucket"]["bucket"], "trend_expansion", "best regime")
    assert_equal(regime["worst_bucket"]["bucket"], "compression_chop", "worst regime")
    assert_true(regime["best_bucket"]["hit_rate_delta"] > 0, "hit-rate delta")
    assert_true(regime["worst_bucket"]["false_positive_rate"] > 0, "false positive")
    assert_true(regime["worst_bucket"]["interactions"]["setup_label"], "setup interaction")
    assert_true(regime["worst_bucket"]["interactions"]["spread_bucket"], "spread interaction")
    confidence = next(item for item in payload.families if item["family"] == "calibrated_confidence")
    assert_equal(confidence["best_bucket"]["bucket"], "medium", "confidence family")
    pattern = next(item for item in payload.families if item["family"] == "symbol_pattern")
    assert_equal(
        pattern["best_bucket"]["bucket"],
        "trend_continuation_with_participation",
        "best pattern",
    )
    assert_equal(
        pattern["worst_bucket"]["bucket"],
        "momentum_deterioration",
        "worst pattern",
    )
    assert_true(payload.summary["calibration_summary"]["market_regime"], "calibration summary")
    guard = next(item for item in payload.rollout_guardrails if item["family"] == "market_regime")
    assert_equal(guard["status"], "eligible_for_review", "guardrail status")
    assert_equal(guard["default_bucket_rate"], 0.0, "default bucket rate")
    assert_equal(guard["stability"]["window_count"], 1, "stability windows")
    assert_equal(guard["stability"]["stable_window_share"], 1.0, "stable share")
    assert_equal(guard["stability"]["daily_window_count"], 1, "daily stability windows")
    assert_equal(guard["stability"]["daily_stable_window_share"], 1.0, "daily stable share")
    assert_equal(guard["stability"]["rolling_window_count"], 2, "rolling stability windows")
    assert_equal(guard["stability"]["rolling_stable_window_share"], 1.0, "rolling stable share")
    assert_true("acceptable_calibration_error" in guard["required_before_authority"], "calibration guard")
    assert_true("non_default_bucket_diversity" in guard["required_before_authority"], "diversity guard")
    execution = next(item for item in payload.families if item["family"] == "execution_quality")
    assert_equal(execution["default_bucket_rate"], 0.6667, "execution default bucket rate")
    assert_true(payload.feature_overlap, "overlap rows")


def test_feature_attribution_caps_default_bucket_collapse():
    rows = [
        {
            "approved": 0,
            "decision_time": f"2026-05-30T10:{idx:02d}:00+00:00",
            "rejected_return_eod": 0.1 if idx % 2 else -0.1,
            "canonical_intelligence_json": _canonical(execution="allow"),
        }
        for idx in range(10)
    ]

    payload = build_feature_attribution_payload(
        rows,
        min_sample_size=5,
        rolling_window_size=5,
    )

    execution_guard = next(
        item for item in payload.rollout_guardrails if item["family"] == "execution_quality"
    )
    execution_family = next(
        item for item in payload.families if item["family"] == "execution_quality"
    )
    assert_equal(execution_family["default_bucket_rate"], 1.0, "collapsed default rate")
    assert_equal(execution_guard["status"], "insufficient_evidence", "default collapse guard")


def test_feature_attribution_reads_historical_analytics_pattern():
    rows = [
        {
            "approved": 1,
            "decision_time": "2026-05-30T10:00:00+00:00",
            "realized_return_pct": 0.8,
            "canonical_intelligence_json": json.dumps(
                {
                    "analytics_state": {
                        "ai_momentum_pattern": {
                            "pattern_label": "historical_continuation",
                            "runtime_effect": "observe_only_no_live_authority",
                        }
                    }
                }
            ),
        },
        {
            "approved": 1,
            "decision_time": "2026-05-30T10:10:00+00:00",
            "realized_return_pct": -0.2,
            "canonical_intelligence_json": json.dumps(
                {
                    "analytics_state": {
                        "ai_momentum_pattern": {
                            "pattern_label": "historical_deterioration",
                            "runtime_effect": "observe_only_no_live_authority",
                        }
                    }
                }
            ),
        },
    ]

    payload = build_feature_attribution_payload(
        rows,
        min_sample_size=1,
        rolling_window_size=1,
    )

    pattern = next(item for item in payload.families if item["family"] == "symbol_pattern")
    assert_equal(
        pattern["best_bucket"]["bucket"],
        "historical_continuation",
        "historical best pattern",
    )
    assert_equal(
        pattern["worst_bucket"]["bucket"],
        "historical_deterioration",
        "historical worst pattern",
    )


def main():
    tests = [
        test_feature_attribution_summarizes_family_deltas_and_guardrails,
        test_feature_attribution_caps_default_bucket_collapse,
        test_feature_attribution_reads_historical_analytics_pattern,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} feature attribution service tests passed.")


if __name__ == "__main__":
    main()
