#!/usr/bin/env python3
"""Focused tests for the macro position-limit hard ceiling (M2a)."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for _p in (ROOT, ROOT / "src", ROOT / "scripts"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from trading_bot.signals.approval.service import run_macro_position_gate


class _Log:
    def warning(self, *a, **k):
        pass

    def info(self, *a, **k):
        pass


def _noop(*a, **k):
    return None


def _call(*, open_count, open_positions=None, allowance=4):
    return run_macro_position_gate(
        symbol="AAPL",
        action="buy",
        price=100.0,
        account_state={
            "open_position_count": open_count,
            "open_positions": open_positions or [],
        },
        context_runtime=None,
        current_et=None,
        macro_risk={"max_new_positions": 8},
        macro_position_count_floor=500.0,
        macro_dust_position_allowance=allowance,
        get_latest_session_momentum=lambda s: None,
        session_momentum_is_fresh=lambda s: False,
        weakest_position_context=lambda a: None,
        evaluate_buy_opportunity=_noop,
        required_buy_confirmations=_noop,
        try_portfolio_rotation=lambda *a: (False, "no_rotation", {}),
        get_account_state=lambda: {},
        sleep=_noop,
        log=_Log(),
    )


def test_macro_hard_ceiling_blocks_total_positions_including_dust():
    # 8 max_new_positions + 4 dust allowance = 12 hard ceiling.
    outcome = _call(open_count=12)
    assert outcome.rejected
    assert outcome.approval.category == "macro_position_limit"
    assert "hard ceiling" in outcome.approval.reason


def test_macro_dust_excluded_positions_below_ceiling_still_allowed():
    # 11 total, all sub-floor dust: effective_count 0 < 8 AND 11 < ceiling 12 -> allowed.
    dust = [{"market_value": 10.0} for _ in range(11)]
    outcome = _call(open_count=11, open_positions=dust)
    assert not outcome.rejected


def test_macro_ceiling_disabled_when_allowance_none():
    # allowance None disables the ceiling; 50 dust positions are still allowed
    # (dust-excluded effective_count 0 < 8), preserving prior behavior.
    dust = [{"market_value": 10.0} for _ in range(50)]
    outcome = _call(open_count=50, open_positions=dust, allowance=None)
    assert not outcome.rejected


if __name__ == "__main__":
    test_macro_hard_ceiling_blocks_total_positions_including_dust()
    test_macro_dust_excluded_positions_below_ceiling_still_allowed()
    test_macro_ceiling_disabled_when_allowance_none()
    print("[OK] macro position gate ceiling tests passed")
