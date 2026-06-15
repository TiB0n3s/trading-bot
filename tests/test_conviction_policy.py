"""Unit tests for conviction-mode config and decision policy.

Pure-logic tests: no broker, DB, or runtime. Run with:

    PYTHONPATH=.:src python -m pytest tests/test_conviction_policy.py -q
"""

from __future__ import annotations

import pytest

from config.conviction import ConvictionConfig, load_conviction_config
from trading_bot.signals.conviction.policy import (
    conviction_active_for_mode,
    conviction_entry_decision,
    conviction_exit_decision,
)


# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
def test_defaults_are_off_and_paper_only():
    cfg = load_conviction_config()
    assert cfg.enabled is False
    assert cfg.paper_only is True
    # Entry bar is above AUTO_BUY default but calibrated to observed score distribution.
    assert cfg.min_score == 23.0
    assert cfg.min_probability_pct == 62.0
    assert cfg.min_system_probability_pct == 80.0


def test_overrides_apply():
    cfg = load_conviction_config(enabled=True, min_score=42.0, max_concurrent_positions=2)
    assert cfg.enabled is True
    assert cfg.min_score == 42.0
    assert cfg.max_concurrent_positions == 2


@pytest.mark.parametrize(
    "field,value",
    [
        ("min_score", 0.0),
        ("min_probability_pct", 150.0),
        ("min_system_probability_pct", 150.0),
        ("max_concurrent_positions", 0),
        ("position_size_pct", 0.0),
        ("position_size_pct", 120.0),
        ("hard_stop_pct", 0.0),
        ("trail_activate_pct", 0.0),
        ("trail_giveback_frac", 0.0),
        ("trail_giveback_frac", 1.0),
        ("take_profit_pct", -1.0),
    ],
)
def test_invalid_config_raises(field, value):
    with pytest.raises(ValueError):
        ConvictionConfig(**{field: value})


# --------------------------------------------------------------------------- #
# Activation
# --------------------------------------------------------------------------- #
def test_active_for_mode():
    disabled = load_conviction_config(enabled=False)
    assert conviction_active_for_mode(disabled, "paper") is False

    paper_only = load_conviction_config(enabled=True, paper_only=True)
    assert conviction_active_for_mode(paper_only, "paper") is True
    assert conviction_active_for_mode(paper_only, "dry_run") is True
    assert conviction_active_for_mode(paper_only, "cash_safe") is False
    assert conviction_active_for_mode(paper_only, "cash_full") is False

    any_mode = load_conviction_config(enabled=True, paper_only=False)
    assert conviction_active_for_mode(any_mode, "cash_full") is True


# --------------------------------------------------------------------------- #
# Entry
# --------------------------------------------------------------------------- #
def _strong_candidate(**over):
    base = {
        "symbol": "MSFT",
        "score": 45.0,
        "probability_pct": 70.0,
        "ml_veto": False,
        "market_context_ok": True,
    }
    base.update(over)
    return base


def _flat_account(open_positions=0):
    return {"open_positions": open_positions}


def _no_recent_trade():
    return {"minutes_since_last_entry": None}


def test_entry_confirmed_on_convergence():
    cfg = load_conviction_config(enabled=True)
    d = conviction_entry_decision(
        candidate=_strong_candidate(),
        account_state=_flat_account(),
        last_trade_state=_no_recent_trade(),
        cfg=cfg,
    )
    assert d["enter"] is True
    assert d["reason"] == "conviction_entry_confirmed"
    assert all(d["checks"].values())


def test_entry_blocked_when_at_capacity():
    cfg = load_conviction_config(enabled=True, max_concurrent_positions=1)
    d = conviction_entry_decision(
        candidate=_strong_candidate(),
        account_state=_flat_account(open_positions=1),
        last_trade_state=_no_recent_trade(),
        cfg=cfg,
    )
    assert d["enter"] is False
    assert d["reason"] == "max_concurrent_positions_reached"


def test_entry_blocked_during_cooldown_and_allowed_after():
    cfg = load_conviction_config(enabled=True, min_minutes_between_entries=240)
    blocked = conviction_entry_decision(
        candidate=_strong_candidate(),
        account_state=_flat_account(),
        last_trade_state={"minutes_since_last_entry": 30},
        cfg=cfg,
    )
    assert blocked["enter"] is False
    assert blocked["reason"] == "entry_cooldown_active"

    allowed = conviction_entry_decision(
        candidate=_strong_candidate(),
        account_state=_flat_account(),
        last_trade_state={"minutes_since_last_entry": 300},
        cfg=cfg,
    )
    assert allowed["enter"] is True


def test_entry_blocked_below_score_bar():
    cfg = load_conviction_config(enabled=True, min_score=30.0)
    d = conviction_entry_decision(
        candidate=_strong_candidate(score=20.0),
        account_state=_flat_account(),
        last_trade_state=_no_recent_trade(),
        cfg=cfg,
    )
    assert d["enter"] is False
    assert d["reason"] == "score_below_conviction_bar"


def test_entry_probability_below_bar():
    cfg = load_conviction_config(enabled=True, min_probability_pct=62.0)
    d = conviction_entry_decision(
        candidate=_strong_candidate(probability_pct=55.0),
        account_state=_flat_account(),
        last_trade_state=_no_recent_trade(),
        cfg=cfg,
    )
    assert d["enter"] is False
    assert d["reason"] == "probability_below_bar"


def test_entry_uses_stricter_bar_for_system_probability_fallback():
    cfg = load_conviction_config(
        enabled=True,
        min_probability_pct=62.0,
        min_system_probability_pct=80.0,
    )
    blocked = conviction_entry_decision(
        candidate=_strong_candidate(
            probability_pct=70.0,
            probability_source="daily_symbol_predictions:probability_of_order",
        ),
        account_state=_flat_account(),
        last_trade_state=_no_recent_trade(),
        cfg=cfg,
    )
    assert blocked["enter"] is False
    assert blocked["reason"] == "probability_below_bar"
    assert blocked["probability_threshold_pct"] == 80.0

    allowed = conviction_entry_decision(
        candidate=_strong_candidate(
            probability_pct=82.0,
            probability_source="daily_symbol_predictions:probability_of_order",
        ),
        account_state=_flat_account(),
        last_trade_state=_no_recent_trade(),
        cfg=cfg,
    )
    assert allowed["enter"] is True
    assert allowed["probability_threshold_pct"] == 80.0


def test_entry_missing_probability_blocks_when_required():
    cfg = load_conviction_config(enabled=True, require_probability=True)
    d = conviction_entry_decision(
        candidate=_strong_candidate(probability_pct=None),
        account_state=_flat_account(),
        last_trade_state=_no_recent_trade(),
        cfg=cfg,
    )
    assert d["enter"] is False
    assert d["reason"] == "probability_unavailable"


def test_entry_missing_probability_allowed_when_not_required():
    cfg = load_conviction_config(enabled=True, require_probability=False)
    d = conviction_entry_decision(
        candidate=_strong_candidate(probability_pct=None),
        account_state=_flat_account(),
        last_trade_state=_no_recent_trade(),
        cfg=cfg,
    )
    assert d["enter"] is True


def test_entry_blocked_on_ml_veto():
    cfg = load_conviction_config(enabled=True, block_on_ml_veto=True)
    d = conviction_entry_decision(
        candidate=_strong_candidate(ml_veto=True),
        account_state=_flat_account(),
        last_trade_state=_no_recent_trade(),
        cfg=cfg,
    )
    assert d["enter"] is False
    assert d["reason"] == "ml_veto"


def test_entry_blocked_on_unfavorable_market_context():
    cfg = load_conviction_config(enabled=True, require_market_context_ok=True)
    d = conviction_entry_decision(
        candidate=_strong_candidate(market_context_ok=False),
        account_state=_flat_account(),
        last_trade_state=_no_recent_trade(),
        cfg=cfg,
    )
    assert d["enter"] is False
    assert d["reason"] == "market_context_unfavorable"


# --------------------------------------------------------------------------- #
# Exit
# --------------------------------------------------------------------------- #
def test_exit_hard_stop_fires_even_within_min_hold():
    cfg = load_conviction_config(enabled=True, hard_stop_pct=3.0, min_hold_minutes=60)
    d = conviction_exit_decision(
        position_state={"unrealized_plpc": -3.5, "minutes_held": 5},
        cfg=cfg,
    )
    assert d["action"] == "exit"
    assert d["reason"] == "hard_stop"


def test_exit_min_hold_guards_non_stop_exits():
    cfg = load_conviction_config(enabled=True, min_hold_minutes=60)
    d = conviction_exit_decision(
        position_state={"unrealized_plpc": 1.0, "high_water_plpc": 1.0, "minutes_held": 10},
        cfg=cfg,
    )
    assert d["action"] == "hold"
    assert d["reason"] == "min_hold_active"


def test_exit_take_profit_when_enabled():
    cfg = load_conviction_config(enabled=True, take_profit_pct=5.0, min_hold_minutes=0)
    d = conviction_exit_decision(
        position_state={"unrealized_plpc": 5.2, "high_water_plpc": 5.2, "minutes_held": 120},
        cfg=cfg,
    )
    assert d["action"] == "exit"
    assert d["reason"] == "take_profit"


def test_exit_trailing_not_engaged_below_activation():
    cfg = load_conviction_config(
        enabled=True, min_hold_minutes=0, trail_activate_pct=3.0, trail_giveback_frac=0.35
    )
    d = conviction_exit_decision(
        position_state={"unrealized_plpc": 2.0, "high_water_plpc": 2.5, "minutes_held": 120},
        cfg=cfg,
    )
    assert d["action"] == "hold"
    assert d["trailing"]["engaged"] is False


def test_exit_trailing_holds_above_floor():
    cfg = load_conviction_config(
        enabled=True, min_hold_minutes=0, trail_activate_pct=3.0, trail_giveback_frac=0.35
    )
    # Peak +10%, floor = 6.5%, current 8% -> hold.
    d = conviction_exit_decision(
        position_state={"unrealized_plpc": 8.0, "high_water_plpc": 10.0, "minutes_held": 120},
        cfg=cfg,
    )
    assert d["action"] == "hold"
    assert d["trailing"]["engaged"] is True
    assert d["trailing"]["floor_plpc"] == pytest.approx(6.5)


def test_exit_trailing_stop_fires_below_floor():
    cfg = load_conviction_config(
        enabled=True, min_hold_minutes=0, trail_activate_pct=3.0, trail_giveback_frac=0.35
    )
    # Peak +10%, floor = 6.5%, current 6% -> exit.
    d = conviction_exit_decision(
        position_state={"unrealized_plpc": 6.0, "high_water_plpc": 10.0, "minutes_held": 120},
        cfg=cfg,
    )
    assert d["action"] == "exit"
    assert d["reason"] == "trailing_stop"


def test_exit_time_stop_when_enabled():
    cfg = load_conviction_config(enabled=True, min_hold_minutes=0, max_hold_minutes=390)
    d = conviction_exit_decision(
        position_state={"unrealized_plpc": 1.0, "high_water_plpc": 1.5, "minutes_held": 400},
        cfg=cfg,
    )
    assert d["action"] == "exit"
    assert d["reason"] == "time_stop"


def test_exit_reversal_protect_only_in_profit():
    cfg = load_conviction_config(enabled=True, min_hold_minutes=0, exit_on_reversal=True)
    in_profit = conviction_exit_decision(
        position_state={
            "unrealized_plpc": 1.5,
            "high_water_plpc": 2.0,
            "minutes_held": 120,
            "ml_bearish": True,
        },
        cfg=cfg,
    )
    assert in_profit["action"] == "exit"
    assert in_profit["reason"] == "reversal_protect"

    # Same reversal signal while flat/negative should not trigger a noise exit
    # (the hard stop is the only downside protection there).
    flat = conviction_exit_decision(
        position_state={
            "unrealized_plpc": -0.5,
            "high_water_plpc": 0.5,
            "minutes_held": 120,
            "momentum_reversal": True,
        },
        cfg=cfg,
    )
    assert flat["action"] == "hold"


def test_exit_default_hold():
    cfg = load_conviction_config(enabled=True, min_hold_minutes=0)
    d = conviction_exit_decision(
        position_state={"unrealized_plpc": 1.0, "high_water_plpc": 1.2, "minutes_held": 120},
        cfg=cfg,
    )
    assert d["action"] == "hold"
    assert d["reason"] == "hold"


def test_exit_handles_missing_fields_gracefully():
    cfg = load_conviction_config(enabled=True, min_hold_minutes=0)
    d = conviction_exit_decision(position_state={}, cfg=cfg)
    assert d["action"] == "hold"
