"""Tests for final sizing safety invariants.

Covers:
  * #6 absolute position-size ceiling (MAX_POSITION_SIZE_PCT backstop).
  * #5 projected per-symbol exposure cap (existing + pending notional),
    applied even on a first entry.
  * #7 macro risk_multiplier clamp to [0, 1] (may only tighten, never amplify).
"""

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))

from risk.macro_policy import apply_macro_overrides
from trading_bot.services.policies.sizing_policy import apply_buy_opportunity_sizing
from trading_bot.services.sizing_service import _apply_final_sizing_invariants


# --- #6: absolute ceiling -----------------------------------------------------

def test_absolute_ceiling_caps_oversized_request():
    caps = _apply_final_sizing_invariants(
        symbol="AAPL", action="buy", final_pct=25.0, account_state={"balance": 100000.0}
    )
    ceiling_caps = [c for c in caps if c.source == "absolute_ceiling"]
    assert ceiling_caps, "expected an absolute_ceiling cap for an oversized request"
    assert ceiling_caps[0].cap_pct == 5.0  # default MAX_POSITION_SIZE_PCT


def test_no_ceiling_cap_for_normal_size():
    caps = _apply_final_sizing_invariants(
        symbol="AAPL", action="buy", final_pct=1.0, account_state={"balance": 100000.0}
    )
    assert not [c for c in caps if c.source == "absolute_ceiling"]


# --- #5: projected per-symbol exposure ---------------------------------------

def test_first_entry_capped_at_per_symbol_exposure():
    # No existing position -> headroom is the full per-symbol cap (4%).
    caps = _apply_final_sizing_invariants(
        symbol="AAPL", action="buy", final_pct=10.0, account_state={"balance": 100000.0}
    )
    proj = [c for c in caps if c.source == "projected_exposure"]
    assert proj, "first entry should be capped to the per-symbol exposure cap"
    assert proj[0].cap_pct == 4.0


def test_existing_position_reduces_headroom():
    # Existing 3% position -> only 1% headroom under the 4% cap.
    account_state = {
        "balance": 100000.0,
        "current_symbol_position": {"qty": 30.0, "current_price": 100.0},  # $3000 = 3%
    }
    caps = _apply_final_sizing_invariants(
        symbol="AAPL", action="buy", final_pct=2.0, account_state=account_state
    )
    proj = [c for c in caps if c.source == "projected_exposure"]
    assert proj, "expected a projected_exposure cap"
    assert proj[0].cap_pct == 1.0
    assert account_state["projected_exposure_cap"]["headroom_pct"] == 1.0


def test_existing_at_cap_yields_zero_headroom():
    account_state = {
        "balance": 100000.0,
        "current_symbol_position": {"qty": 40.0, "current_price": 100.0},  # $4000 = 4%
    }
    caps = _apply_final_sizing_invariants(
        symbol="AAPL", action="buy", final_pct=1.0, account_state=account_state
    )
    proj = [c for c in caps if c.source == "projected_exposure"]
    assert proj and proj[0].cap_pct == 0.0  # zero size -> order will not route


def test_sell_action_skips_exposure_cap():
    caps = _apply_final_sizing_invariants(
        symbol="AAPL", action="sell", final_pct=10.0, account_state={"balance": 100000.0}
    )
    assert not [c for c in caps if c.source == "projected_exposure"]


# --- #7: macro risk_multiplier clamp -----------------------------------------

def test_macro_override_clamps_amplifying_multiplier():
    out = apply_macro_overrides({"risk_multiplier": 1.0}, {"risk_multiplier": 3.0})
    assert out["risk_multiplier"] == 1.0  # clamped down from 3.0


def test_macro_override_allows_tightening_multiplier():
    out = apply_macro_overrides({"risk_multiplier": 1.0}, {"risk_multiplier": 0.5})
    assert out["risk_multiplier"] == 0.5


def test_sizing_clamps_amplifying_multiplier():
    account_state = {"buy_opportunity": {"buy_opportunity_recommendation": "avoid"}}
    # Even if an unclamped 2.0 reaches sizing, it cannot amplify above base.
    final_pct = apply_buy_opportunity_sizing(
        symbol="AAPL",
        action="buy",
        base_position_size_pct=1.0,
        risk_multiplier=2.0,
        account_state=account_state,
    )
    assert final_pct <= 1.0
