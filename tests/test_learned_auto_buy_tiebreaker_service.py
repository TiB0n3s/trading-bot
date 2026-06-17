"""Tests for learned auto-buy tie-breaker evidence qualification."""

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.learned_auto_buy_tiebreaker_service import (
    LearnedAutoBuyThresholds,
    LearnedAutoBuyTiebreakerService,
)


class FakeRepo:
    def __init__(self, rows):
        self.rows = rows
        self.calls = []

    def rows_between(
        self,
        start_date,
        end_date,
        *,
        symbol=None,
        candidate_kind=None,
        candidate_statuses=None,
        limit=None,
    ):
        self.calls.append(
            {
                "start_date": start_date,
                "end_date": end_date,
                "symbol": symbol,
                "candidate_kind": candidate_kind,
                "candidate_statuses": candidate_statuses,
                "limit": limit,
            }
        )
        return list(self.rows)


def _row(symbol, pattern, ret, mfe, mae=-0.2):
    return {
        "symbol": symbol,
        "candidate_json": json.dumps(
            {
                "candidate": {"symbol_pattern": pattern},
                "forward_return_pct": ret,
                "forward_mfe_pct": mfe,
                "forward_mae_pct": mae,
            }
        ),
    }


def test_learned_tiebreaker_qualifies_symbol_pattern_bucket():
    rows = [_row("AAPL", "trend_reclaim", 0.6, 1.4) for _ in range(12)]
    rows.extend(_row("MSFT", "trend_reclaim", -0.4, 0.3) for _ in range(12))
    service = LearnedAutoBuyTiebreakerService(
        FakeRepo(rows),
        LearnedAutoBuyThresholds(
            min_sample_size=10,
            min_win_rate=0.55,
            min_avg_return_pct=0.2,
            min_avg_mfe_pct=1.0,
            max_avg_mae_pct=-1.5,
            lookback_days=5,
        ),
    )

    decision = service.decide(
        {"symbol": "AAPL", "symbol_pattern": "trend_reclaim"},
        target_date="2026-06-03",
    )

    assert decision.qualified is True
    assert decision.reason == "symbol_pattern_bucket_passed"
    assert decision.evidence["qualified_bucket"] == "symbol_pattern"
    assert decision.evidence["symbol_pattern_stats"]["sample_size"] == 12


def test_learned_tiebreaker_rejects_thin_or_negative_bucket():
    rows = [_row("AAPL", "messy_chop", -0.2, 0.4) for _ in range(12)]
    service = LearnedAutoBuyTiebreakerService(
        FakeRepo(rows),
        LearnedAutoBuyThresholds(min_sample_size=10),
    )

    decision = service.decide(
        {"symbol": "AAPL", "symbol_pattern": "messy_chop"},
        target_date="2026-06-03",
    )

    assert decision.qualified is False
    assert decision.reason == "historical_bucket_below_thresholds"


def test_learned_tiebreaker_passes_historical_row_limit_to_repository():
    repo = FakeRepo([_row("AAPL", "trend_reclaim", 0.6, 1.4)])
    service = LearnedAutoBuyTiebreakerService(
        repo,
        LearnedAutoBuyThresholds(min_sample_size=10, max_historical_rows=123),
    )

    service.decide(
        {"symbol": "AAPL", "symbol_pattern": "trend_reclaim"},
        target_date="2026-06-03",
    )

    assert repo.calls[0]["limit"] == 123
    assert repo.calls[0]["candidate_statuses"] == ("near_threshold", "taken")


if __name__ == "__main__":
    test_learned_tiebreaker_qualifies_symbol_pattern_bucket()
    test_learned_tiebreaker_rejects_thin_or_negative_bucket()
    test_learned_tiebreaker_passes_historical_row_limit_to_repository()
    print("learned auto-buy tiebreaker service tests passed")
