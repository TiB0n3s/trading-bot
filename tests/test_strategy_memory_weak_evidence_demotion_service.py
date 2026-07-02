"""Tests for weak strategy-memory demotion replay."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.services.strategy_memory_weak_evidence_demotion_service import (  # noqa: E402
    StrategyMemoryDemotionConfig,
    replay_strategy_memory_weak_evidence_demotion,
)


def test_weak_memory_rows_become_watch_only_when_no_other_hard_blockers():
    rows = [
        {
            "timestamp": "2026-06-30T10:00:00-04:00",
            "symbol": "AAPL",
            "decision": "skip",
            "score": 14.0,
            "hard_block_reason": "strategy_memory_avoid_weak_evidence:no symbol memory",
            "return_60m": 0.7,
        },
        {
            "timestamp": "2026-06-30T10:05:00-04:00",
            "symbol": "MSFT",
            "decision": "skip",
            "score": 12.0,
            "hard_block_reason": "strategy_memory_avoid_weak_evidence:sample size too small",
            "return_60m": -0.2,
        },
        {
            "timestamp": "2026-06-30T10:10:00-04:00",
            "symbol": "NVDA",
            "decision": "skip",
            "score": 14.0,
            "hard_block_reason": (
                "setup_avoid:weak; "
                "strategy_memory_avoid_weak_evidence:no symbol memory"
            ),
            "return_60m": 1.0,
        },
        {
            "timestamp": "2026-06-30T10:15:00-04:00",
            "symbol": "TSLA",
            "decision": "skip",
            "score": 14.0,
            "hard_block_reason": (
                "bias_avoid:soft; "
                "strategy_memory_avoid_weak_evidence:sample size too small"
            ),
            "return_60m": 0.5,
        },
        {
            "timestamp": "2026-06-30T10:20:00-04:00",
            "symbol": "META",
            "decision": "watch",
            "score": 14.0,
            "return_60m": 0.1,
        },
    ]

    payload = replay_strategy_memory_weak_evidence_demotion(
        rows,
        config=StrategyMemoryDemotionConfig(),
    )

    assert payload["runtime_effect"] == "diagnostic_only_no_live_authority"
    assert payload["eligible_rows"] == 3
    assert payload["would_watch_rows"] == 2
    assert payload["remaining_context_block_rows"] == 1
    assert payload["ineligible_other_setup_tape_ml_chase_rows"] == 1
    assert payload["would_watch_summary"]["known_outcome_rows"] == 2
    assert payload["would_watch_summary"]["profitable_rows"] == 1
    assert payload["would_watch_summary"]["negative_rows"] == 1
    assert payload["would_watch_summary"]["avg_return_pct"] == 0.25
    assert payload["baseline_no_hard_block_summary"]["avg_return_pct"] == 0.1
    assert payload["ev_delta_vs_no_hard_block_pct"] == 0.15
    assert payload["passes_net_ev_guard"] is True


def test_requires_explicit_weak_reason_and_near_threshold_score():
    rows = [
        {
            "timestamp": "2026-06-30T10:00:00-04:00",
            "symbol": "AAPL",
            "score": 14.0,
            "hard_block_reason": "strategy_memory_avoid_weak_evidence:manual seed",
            "return_60m": 2.0,
        },
        {
            "timestamp": "2026-06-30T10:05:00-04:00",
            "symbol": "MSFT",
            "score": 9.5,
            "hard_block_reason": "strategy_memory_avoid_weak_evidence:no symbol memory",
            "return_60m": 2.0,
        },
    ]

    payload = replay_strategy_memory_weak_evidence_demotion(
        rows,
        config=StrategyMemoryDemotionConfig(),
    )

    assert payload["eligible_rows"] == 0
    assert payload["would_watch_rows"] == 0
    assert payload["passes_net_ev_guard"] is False
