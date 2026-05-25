#!/usr/bin/env python3
"""
Targeted tests for macro risk policy mapping.

These tests use temporary directories and temporary market_context.json files.
They do not touch the live market_context.json.

Run:
  python3 tests/test_macro_risk.py
"""

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from macro_risk import get_macro_risk


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def write_context(tmpdir, macro_sentiment):
    p = Path(tmpdir) / "market_context.json"
    p.write_text(json.dumps({
        "market_date": "2099-01-01",
        "macro_sentiment": macro_sentiment,
        "symbols": {}
    }))
    return p


def test_missing_context_defaults_safe():
    with tempfile.TemporaryDirectory() as d:
        result = get_macro_risk(Path(d))

    assert_equal(result["macro_regime"], "unknown", "missing macro_regime")
    assert_equal(result["risk_multiplier"], 0.75, "missing risk_multiplier")
    assert_equal(result["max_new_positions"], 8, "missing max positions")
    assert_equal(result["block_new_buys"], False, "missing block buys")


def test_risk_on_policy():
    with tempfile.TemporaryDirectory() as d:
        write_context(d, "risk-on")
        result = get_macro_risk(Path(d))

    assert_equal(result["macro_regime"], "risk_on", "risk-on regime")
    assert_equal(result["risk_multiplier"], 1.0, "risk-on multiplier")
    assert_equal(result["max_new_positions"], 12, "risk-on max positions")
    assert_equal(result["block_new_buys"], False, "risk-on block buys")


def test_neutral_policy():
    with tempfile.TemporaryDirectory() as d:
        write_context(d, "neutral")
        result = get_macro_risk(Path(d))

    assert_equal(result["macro_regime"], "neutral", "neutral regime")
    assert_equal(result["risk_multiplier"], 0.75, "neutral multiplier")
    assert_equal(result["max_new_positions"], 8, "neutral max positions")
    assert_equal(result["block_new_buys"], False, "neutral block buys")


def test_defensive_policy():
    with tempfile.TemporaryDirectory() as d:
        write_context(d, "defensive")
        result = get_macro_risk(Path(d))

    assert_equal(result["macro_regime"], "defensive", "defensive regime")
    assert_equal(result["risk_multiplier"], 0.5, "defensive multiplier")
    assert_equal(result["max_new_positions"], 5, "defensive max positions")
    assert_equal(result["block_new_buys"], False, "defensive block buys")


def test_capital_preservation_policy():
    with tempfile.TemporaryDirectory() as d:
        write_context(d, "capital_preservation")
        result = get_macro_risk(Path(d))

    assert_equal(result["macro_regime"], "capital_preservation", "capital preservation regime")
    assert_equal(result["risk_multiplier"], 0.0, "capital preservation multiplier")
    assert_equal(result["max_new_positions"], 0, "capital preservation max positions")
    assert_equal(result["block_new_buys"], True, "capital preservation block buys")


def main():
    tests = [
        test_missing_context_defaults_safe,
        test_risk_on_policy,
        test_neutral_policy,
        test_defensive_policy,
        test_capital_preservation_policy,
    ]

    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print()
    print(f"All {len(tests)} macro risk tests passed.")


if __name__ == "__main__":
    main()
