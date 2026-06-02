#!/usr/bin/env python3
"""Tests for observe-only symbol pattern outcome diagnostics."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.symbol_pattern_outcome_service import (
    SYMBOL_PATTERN_OUTCOME_REPORT_VERSION,
    build_symbol_pattern_outcome_payload,
)


def test_pattern_outcomes_and_governance_are_diagnostic_only():
    rows = [
        {
            "symbol": "AAPL",
            "approved": 1,
            "symbol_pattern": "trend_continuation_with_participation",
            "pattern_source": "canonical_pattern_state",
            "pattern_runtime_effect": "observe_only_no_live_authority",
            "market_regime": "trend_expansion",
            "setup_label": "breakout",
            "session_phase": "first_30m",
            "execution_cost_bucket": "low_cost",
            "volatility_chase_risk": "normal",
            "exit_trigger": "target",
            "realized_return_pct": 0.80,
            "mfe_pct": 1.20,
            "max_adverse_excursion_pct": -0.20,
            "capture_ratio": 0.67,
            "missed_upside_pct": 0.10,
        },
        {
            "symbol": "MSFT",
            "approved": 1,
            "symbol_pattern": "momentum_deterioration",
            "pattern_source": "canonical_pattern_state",
            "pattern_runtime_effect": "observe_only_no_live_authority",
            "market_regime": "compression_chop",
            "setup_label": "late_chase",
            "session_phase": "midday",
            "execution_cost_bucket": "high_cost",
            "volatility_chase_risk": "high",
            "exit_trigger": "trail",
            "realized_return_pct": -0.40,
            "mfe_pct": 0.30,
            "max_adverse_excursion_pct": -0.80,
            "capture_ratio": 0.0,
            "missed_upside_pct": 0.30,
        },
        {
            "symbol": "NVDA",
            "approved": 0,
            "symbol_pattern": "momentum_deterioration",
            "pattern_source": "derived_from_canonical_sections",
            "pattern_runtime_effect": "observe_only_no_live_authority",
            "market_regime": "compression_chop",
            "setup_label": "late_chase",
            "session_phase": "midday",
            "execution_cost_bucket": "moderate_cost",
            "volatility_chase_risk": "high",
            "rejected_return_60m": -0.60,
            "rejected_max_favorable_60m": 0.10,
            "rejected_max_adverse_60m": -0.90,
        },
    ]

    payload = build_symbol_pattern_outcome_payload(rows, min_sample_size=2)

    assert payload.summary["report_version"] == SYMBOL_PATTERN_OUTCOME_REPORT_VERSION
    assert payload.summary["runtime_effect"] == "diagnostic_only_no_live_authority"
    assert payload.summary["rows_with_outcome"] == 3
    deteriorating = next(
        item for item in payload.pattern_outcomes if item["pattern"] == "momentum_deterioration"
    )
    assert deteriorating["sample_size"] == 2
    assert deteriorating["hit_rate"] == 0.0
    assert deteriorating["ev_pct"] == -0.5
    governance = next(
        item for item in payload.rollout_governance if item["pattern"] == "momentum_deterioration"
    )
    assert governance["status"] == "narrow_block_candidate"
    assert governance["runtime_effect"] == "diagnostic_only_no_live_authority"
    assert any(item["interaction"] == "market_regime" for item in payload.calibration_buckets)
    assert any("exit=trail" in item["bucket"] for item in payload.exit_patterns)


def test_no_rows_returns_quality_warning():
    payload = build_symbol_pattern_outcome_payload([], min_sample_size=5)

    assert payload.summary["rows"] == 0
    assert payload.quality_warnings[0]["warning"] == "no_rows"


def main():
    tests = [
        test_pattern_outcomes_and_governance_are_diagnostic_only,
        test_no_rows_returns_quality_warning,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} symbol pattern outcome tests passed.")


if __name__ == "__main__":
    main()
