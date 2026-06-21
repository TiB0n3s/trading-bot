#!/usr/bin/env python3
"""Unit tests for AccountStateView, the typed read-view over account_state."""
# ruff: noqa: E402

from __future__ import annotations

import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from trading_bot.signals.context.account_state_view import AccountStateView

SECTION_FIELDS = [
    "setup_quality",
    "buy_opportunity",
    "prediction_gate",
    "session_momentum_gate",
    "momentum",
    "tape",
    "conviction_stack",
    "market_alignment",
    "setup_observation",
]
SCALAR_FIELDS = ["symbol", "action", "max_position_size_pct_override"]


def _populated_state():
    return {
        "symbol": "AAPL",
        "action": "buy",
        "max_position_size_pct_override": 0.75,
        "setup_quality": {"score": 80, "recommendation": "buy"},
        "buy_opportunity": {"buy_opportunity_score": 11},
        "prediction_gate": {"deterministic_signal_quality_decision": "pass"},
        "session_momentum_gate": {"severity": "pass"},
        "momentum": {"momentum_state": "accelerating"},
        "tape": {"label": "clean_momentum"},
        "conviction_stack": {"dominant_limiter": "none"},
        "market_alignment": {"bias": "neutral"},
        "setup_observation": {"policy_action": "allow"},
    }


def test_from_none_yields_empty_view():
    view = AccountStateView.from_account_state(None)
    for field in SCALAR_FIELDS:
        assert getattr(view, field) is None
    for field in SECTION_FIELDS:
        assert getattr(view, field) == {}


def test_section_accessors_match_get_or_empty_idiom():
    state = _populated_state()
    view = AccountStateView.from_account_state(state)
    for field in SECTION_FIELDS:
        assert getattr(view, field) == (state.get(field) or {})


def test_scalar_accessors_match_plain_get():
    state = _populated_state()
    view = AccountStateView.from_account_state(state)
    for field in SCALAR_FIELDS:
        assert getattr(view, field) == state.get(field)


def test_missing_scalars_are_none_and_missing_sections_are_empty():
    view = AccountStateView.from_account_state({})
    for field in SCALAR_FIELDS:
        assert getattr(view, field) is None
    for field in SECTION_FIELDS:
        assert getattr(view, field) == {}


def test_falsy_section_defaults_to_empty_dict():
    # Mirrors `account_state.get("x") or {}` — None/0/"" all collapse to {}.
    view = AccountStateView.from_account_state({"setup_quality": None, "tape": 0})
    assert view.setup_quality == {}
    assert view.tape == {}


def test_escape_hatch_get_and_contains_and_raw():
    state = {"some_unmodelled_key": 123}
    view = AccountStateView.from_account_state(state)
    assert view.get("some_unmodelled_key") == 123
    assert view.get("absent", "fallback") == "fallback"
    assert "some_unmodelled_key" in view
    assert "absent" not in view
    # raw is the SAME object (no copy) so the view stays consistent with the dict.
    assert view.raw is state


def test_view_reflects_later_mutations_to_underlying_dict():
    state = {}
    view = AccountStateView.from_account_state(state)
    assert view.setup_quality == {}
    state["setup_quality"] = {"score": 90}
    assert view.setup_quality == {"score": 90}


def test_view_is_frozen():
    view = AccountStateView.from_account_state({})
    with pytest.raises(Exception):
        view.raw = {"x": 1}  # type: ignore[misc]
