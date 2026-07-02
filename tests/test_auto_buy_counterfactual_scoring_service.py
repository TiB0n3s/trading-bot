"""Tests for observe-only auto-buy counterfactual scoring."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.services.auto_buy_counterfactual_scoring_service import (  # noqa: E402
    ScoreReplayConfig,
    parse_reason_tokens,
    replay_counterfactual_scores,
    variant_score,
)


def test_family_cap_and_context_collapse_adjust_only_duplicate_penalties():
    reason = (
        "negative_session_downtrend:-4;"
        "15m_falling:-3;"
        "30m_falling:-3;"
        "60m_falling:-2;"
        "120m_falling:-2;"
        "below_vwap:-1;"
        "structural_downtrend:-3;"
        "bias_avoid:unspecified:-5;"
        "risk_high:-2"
    )
    tokens = parse_reason_tokens(reason)

    assert variant_score(6.0, tokens, "tape_cap_-8") == 16.0
    assert variant_score(6.0, tokens, "tape_cap_-10") == 14.0
    assert variant_score(6.0, tokens, "context_risk_collapsed") == 8.0
    assert variant_score(6.0, tokens, "tape_cap_-8_context_risk_collapsed") == 18.0


def test_counterfactual_summary_counts_profitable_and_losing_score_unlocks():
    rows = [
        {
            "timestamp": "2026-06-30T10:00:00-04:00",
            "symbol": "AAPL",
            "decision": "skip",
            "score": 6.0,
            "reason": (
                "negative_session_downtrend:-4;"
                "15m_falling:-3;"
                "30m_falling:-3;"
                "below_vwap:-1;"
                "structural_downtrend:-3;"
                "bias_avoid:unspecified:-5;"
                "risk_high:-2"
            ),
            "hard_block_reason": "negative_session:downtrend",
            "return_60m": 1.2,
            "forward_mfe_pct": 2.4,
        },
        {
            "timestamp": "2026-06-30T10:05:00-04:00",
            "symbol": "MSFT",
            "decision": "skip",
            "score": 6.0,
            "reason": (
                "negative_session_fading:-4;"
                "15m_falling:-3;"
                "30m_falling:-3;"
                "below_vwap:-1;"
                "structural_downtrend:-3;"
                "bias_avoid:unspecified:-5;"
                "risk_high:-2"
            ),
            "return_60m": -0.4,
            "forward_mfe_pct": 0.1,
        },
    ]

    payload = replay_counterfactual_scores(rows, config=ScoreReplayConfig())
    by_variant = {row["variant"]: row for row in payload["variants"]}
    recommended = by_variant["tape_cap_-8_context_risk_collapsed"]

    assert payload["runtime_effect"] == "diagnostic_only_no_live_authority"
    assert recommended["score_unlocks"] == 2
    assert recommended["profitable_unlocks"] == 1
    assert recommended["losing_unlocks"] == 1
    assert recommended["still_hard_blocked_unlocks"] == 1
    assert recommended["avg_unlock_return_pct"] == 0.4


if __name__ == "__main__":
    test_family_cap_and_context_collapse_adjust_only_duplicate_penalties()
    test_counterfactual_summary_counts_profitable_and_losing_score_unlocks()
    print("auto-buy counterfactual scoring service tests passed")
