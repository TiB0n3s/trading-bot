"""Tests for the net-EV-after-costs estimator and bar (#11)."""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.services.ev_after_costs import (
    DEFAULT_EV_AFTER_COST_MIN_PCT,
    clears_ev_bar,
    estimate_net_ev_after_cost_pct,
)


def test_ev_basic_positive():
    # p=0.6, reward=1.0, risk=0.5 -> 0.6*1.0 - 0.4*0.5 = 0.4
    ev = estimate_net_ev_after_cost_pct(prob_win=0.6, reward_pct=1.0, risk_pct=0.5)
    assert round(ev, 4) == 0.4


def test_ev_subtracts_extra_costs():
    ev = estimate_net_ev_after_cost_pct(
        prob_win=0.6, reward_pct=1.0, risk_pct=0.5, extra_cost_pct=0.1
    )
    assert round(ev, 4) == 0.3


def test_ev_negative_when_edge_too_thin():
    # p=0.5, symmetric reward/risk -> 0 EV, below the +0.25% bar
    ev = estimate_net_ev_after_cost_pct(prob_win=0.5, reward_pct=0.8, risk_pct=0.8)
    assert ev == 0.0
    assert clears_ev_bar(ev) is False


def test_ev_prob_clamped():
    # prob > 1 is clamped to 1.0 -> EV == reward
    ev = estimate_net_ev_after_cost_pct(prob_win=1.5, reward_pct=1.0, risk_pct=0.5)
    assert ev == 1.0


def test_clears_bar_at_threshold():
    assert clears_ev_bar(DEFAULT_EV_AFTER_COST_MIN_PCT) is True
    assert clears_ev_bar(0.24) is False
    assert clears_ev_bar(0.25) is True
