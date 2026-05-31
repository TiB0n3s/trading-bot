#!/usr/bin/env python3
"""Tests for intelligence decision-context summaries."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from decision_context import build_intelligence_context


def test_summary_prefers_canonical_setup_quality_over_legacy_observation():
    account_state = {
        "setup_quality": {
            "label": "avoid_far_below_vwap_chase",
            "recommendation": "avoid",
            "source": "setup_engine",
        },
        "setup_observation": {
            "setup_label": "legacy_supportive_label",
            "setup_policy_action": "allow",
        },
    }

    with patch("decision_context.load_portfolio_replacement_memory", return_value={}):
        ctx = build_intelligence_context("AAPL", "buy", account_state)

    assert ctx["setup"] == account_state["setup_quality"]
    assert ctx["setup_quality"] == account_state["setup_quality"]
    assert ctx["setup_observation"] == account_state["setup_observation"]
    assert ctx["summary"]["recommended_action"] == "block_preferred"
    assert any("setup quality caution" in risk for risk in ctx["summary"]["primary_risks"])
    assert not any("legacy_supportive_label" in item for item in ctx["summary"]["primary_supports"])


def test_summary_uses_setup_quality_source_for_supportive_context():
    account_state = {
        "setup_quality": {
            "label": "confirmed_near_vwap_recovery",
            "recommendation": "favorable",
            "source": "setup_engine",
        },
        "setup_observation": {
            "setup_label": "legacy_label",
            "setup_policy_action": "block",
        },
    }

    with patch("decision_context.load_portfolio_replacement_memory", return_value={}):
        ctx = build_intelligence_context("AAPL", "buy", account_state)

    assert ctx["summary"]["recommended_action"] == "allow"
    assert any(
        "setup quality supportive (confirmed_near_vwap_recovery, source=setup_engine)" in support
        for support in ctx["summary"]["primary_supports"]
    )


def main():
    tests = [
        test_summary_prefers_canonical_setup_quality_over_legacy_observation,
        test_summary_uses_setup_quality_source_for_supportive_context,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} decision context tests passed.")


if __name__ == "__main__":
    main()
