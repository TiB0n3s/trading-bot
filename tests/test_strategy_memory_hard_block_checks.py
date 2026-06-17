#!/usr/bin/env python3
"""Tests for strategy-memory hard-block attribution reporting."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from trading_bot.ops_checks.commands.strategy_memory_hard_block_checks import (  # noqa: E402
    build_strategy_memory_hard_block_rows,
)


def test_build_strategy_memory_hard_block_rows_decomposes_bar_pattern_and_costs():
    rows = [
        {
            "candidate_ts": "2026-06-16T15:04:06.110388-04:00",
            "symbol": "OKTA",
            "score": 26.0,
            "decision": "skip",
            "setup_label": "above_vwap_neutral_continuation",
            "candidate_json": json.dumps(
                {
                    "candidate": {
                        "bid": 117.41,
                        "ask": 117.60,
                        "hard_block_reason": (
                            "strategy_memory_avoid:setup_score=46.0<learned_min=70;mixed results"
                        ),
                        "reason": (
                            "strategy_memory:avoid:min_setup=70:trades=5; "
                            "bar_pattern_memory:avoid:bearish_divergence:"
                            "unknown|insufficient_forward_bars; "
                            "strategy_memory_avoid_setup_below_min:46.0<70"
                        ),
                    },
                    "forward_reference_price": 117.505,
                    "return_60m": 0.25,
                    "max_favorable_60m": 0.50,
                    "max_adverse_60m": -0.10,
                    "label_status": "labeled",
                }
            ),
        }
    ]

    review_rows = build_strategy_memory_hard_block_rows(rows)

    assert len(review_rows) == 1
    row = review_rows[0]
    assert row["primary_blocker"] == "strategy_memory_avoid"
    assert row["weak_evidence"] is False
    assert row["memory_recommendation"] == "avoid"
    assert row["memory_min_setup_score"] == 70.0
    assert row["memory_trades"] == 5.0
    assert row["bar_pattern_recommendation"] == "avoid"
    assert row["bar_pattern_label"] == "bearish_divergence"
    assert row["bar_pattern_key"] == "unknown|insufficient_forward_bars"
    assert row["has_forward_outcome"] is True
    assert row["spread_cost_pct"] == 0.1617
    assert row["net_return_60m_after_spread"] == 0.0883


def test_build_strategy_memory_hard_block_rows_flags_weak_evidence_probe_candidates():
    rows = [
        {
            "candidate_ts": "2026-06-16T15:56:08.280750-04:00",
            "symbol": "VZ",
            "score": 25.0,
            "decision": "skip",
            "setup_label": "above_vwap_strength_continuation",
            "candidate_json": json.dumps(
                {
                    "candidate": {
                        "bid": 46.80,
                        "ask": 46.81,
                        "hard_block_reason": (
                            "strategy_memory_avoid_weak_evidence:"
                            "setup_score=60.0<learned_min=70;no symbol memory for VZ"
                        ),
                        "reason": (
                            "strategy_memory:avoid:min_setup=70:trades=None; "
                            "bar_pattern_memory:avoid:volume_confirmed_breakout:"
                            "unknown|insufficient_forward_bars"
                        ),
                    },
                    "forward_reference_price": 46.805,
                    "return_eod": 0.010683,
                    "max_favorable_60m": 0.010683,
                    "max_adverse_60m": -0.021365,
                    "label_status": "partial",
                    "partial_reason": "near_close_no_60m_window",
                }
            ),
        }
    ]

    review_rows = build_strategy_memory_hard_block_rows(rows)

    assert len(review_rows) == 1
    row = review_rows[0]
    assert row["primary_blocker"] == "strategy_memory_avoid_weak_evidence"
    assert row["weak_evidence"] is True
    assert row["memory_trades"] is None
    assert row["bar_pattern_label"] == "volume_confirmed_breakout"
    assert row["return_60m"] is None
    assert row["return_eod"] == 0.010683
    assert row["has_forward_outcome"] is True


if __name__ == "__main__":
    test_build_strategy_memory_hard_block_rows_decomposes_bar_pattern_and_costs()
    test_build_strategy_memory_hard_block_rows_flags_weak_evidence_probe_candidates()
