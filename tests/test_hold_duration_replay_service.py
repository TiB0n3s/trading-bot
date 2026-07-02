"""Tests for read-only hold-duration replay calculations."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from trading_bot.services.hold_duration_replay_service import (  # noqa: E402
    HoldDurationReplayConfig,
    HoldDurationReplayService,
)


class FakeRepo:
    def auto_buy_candidates_between(self, start_date, end_date, *, limit=None):
        return [
            {
                "id": 1,
                "timestamp": "2026-06-30T10:00:00-04:00",
                "symbol": "AAPL",
                "signal_source": "internal_all",
                "decision": "watch",
                "score": 12.0,
                "setup_score": 65.0,
                "hard_block_reason": "",
                "order_submitted": 0,
            },
            {
                "id": 2,
                "timestamp": "2026-06-30T10:00:00-04:00",
                "symbol": "MSFT",
                "signal_source": "internal_all",
                "decision": "skip",
                "score": 8.0,
                "setup_score": 20.0,
                "hard_block_reason": "setup_avoid; strategy_memory_avoid_weak_evidence",
                "order_submitted": 0,
            },
        ][:limit or None]

    def feature_price_points(self, symbols, start_date, end_date):
        return [
            {
                "timestamp": "2026-06-30T10:00:00-04:00",
                "symbol": "AAPL",
                "last_price": 100.0,
                "pattern_label": "constructive_continuation",
                "pattern_score": 82.0,
                "opportunity_action": "buy_candidate",
                "opportunity_quality": "best_buy_window",
                "long_opportunity_score": 91.0,
                "sell_opportunity_score": 12.0,
            },
            {"timestamp": "2026-06-30T10:15:00-04:00", "symbol": "AAPL", "last_price": 101.0},
            {"timestamp": "2026-06-30T11:00:00-04:00", "symbol": "AAPL", "last_price": 102.0},
            {"timestamp": "2026-06-30T16:00:00-04:00", "symbol": "AAPL", "last_price": 103.0},
            {"timestamp": "2026-07-01T16:00:00-04:00", "symbol": "AAPL", "last_price": 104.0},
            {
                "timestamp": "2026-06-30T10:00:00-04:00",
                "symbol": "MSFT",
                "last_price": 200.0,
                "pattern_label": "bearish_distribution",
                "pattern_score": 22.0,
                "opportunity_action": "sell_or_avoid_candidate",
                "opportunity_quality": "best_sell_or_avoid_window",
                "long_opportunity_score": 18.0,
                "sell_opportunity_score": 94.0,
            },
            {"timestamp": "2026-06-30T10:15:00-04:00", "symbol": "MSFT", "last_price": 198.0},
            {"timestamp": "2026-06-30T11:00:00-04:00", "symbol": "MSFT", "last_price": 196.0},
            {"timestamp": "2026-06-30T16:00:00-04:00", "symbol": "MSFT", "last_price": 197.0},
            {"timestamp": "2026-07-01T16:00:00-04:00", "symbol": "MSFT", "last_price": 195.0},
        ]


class PatternGateRepo:
    def auto_buy_candidates_between(self, start_date, end_date, *, limit=None):
        rows = []
        for idx in range(100):
            rows.append(
                {
                    "id": idx + 1,
                    "timestamp": "2026-06-30T10:00:00-04:00",
                    "symbol": f"T{idx:03d}",
                    "signal_source": "internal_all",
                    "decision": "skip",
                    "score": 8.0,
                    "setup_score": 60.0,
                    "hard_block_reason": "setup_avoid",
                    "order_submitted": 0,
                }
            )
        return rows[:limit or None]

    def feature_price_points(self, symbols, start_date, end_date):
        rows = []
        for idx in range(100):
            symbol = f"T{idx:03d}"
            winning = idx >= 10
            exit_price = 101.0 if winning else 99.0
            rows.extend(
                [
                    {
                        "timestamp": "2026-06-30T10:00:00-04:00",
                        "symbol": symbol,
                        "last_price": 100.0,
                        "pattern_label": "constructive_continuation",
                        "pattern_score": 80.0,
                        "opportunity_action": "buy_candidate",
                        "opportunity_quality": "good_buy_window",
                        "long_opportunity_score": float(idx),
                        "sell_opportunity_score": 10.0,
                    },
                    {
                        "timestamp": "2026-06-30T10:15:00-04:00",
                        "symbol": symbol,
                        "last_price": exit_price,
                    },
                ]
            )
        return rows


def _row(rows, label):
    return next(row for row in rows if row["label"] == label)


def test_hold_duration_replay_computes_fixed_horizon_and_policy_stats():
    service = HoldDurationReplayService(FakeRepo(), HoldDurationReplayConfig(cost_bps=0.0))

    payload = service.report("2026-06-30", lookback_days=0)

    assert payload["candidate_rows"] == 2
    fixed_15m = _row(payload["horizons"], "15m")
    assert fixed_15m["rows"] == 2
    assert fixed_15m["avg_net_return_pct"] == 0.0
    assert fixed_15m["positive_rate_pct"] == 50.0

    hold_winners_60m = _row(payload["policy_replays"], "hold_15m_winners_to_60m")
    assert hold_winners_60m["rows"] == 2
    assert hold_winners_60m["extended_rows"] == 1
    assert hold_winners_60m["avg_net_return_pct"] == 0.5

    winners_60m = _row(payload["winner_cohorts"]["15m_winners"], "60m")
    losers_60m = _row(payload["winner_cohorts"]["15m_losers"], "60m")
    assert winners_60m["avg_net_return_pct"] == 2.0
    assert losers_60m["avg_net_return_pct"] == -2.0


def test_hold_duration_replay_applies_round_trip_cost_bps():
    service = HoldDurationReplayService(FakeRepo(), HoldDurationReplayConfig(cost_bps=10.0))

    payload = service.report("2026-06-30", lookback_days=0)

    fixed_15m = _row(payload["horizons"], "15m")
    assert fixed_15m["avg_gross_return_pct"] == 0.0
    assert fixed_15m["avg_net_return_pct"] == -0.1


def test_hold_duration_replay_uses_realistic_default_cost_bps():
    service = HoldDurationReplayService(FakeRepo())

    payload = service.report("2026-06-30", lookback_days=0)

    assert payload["cost_bps"] == 16.0
    fixed_15m = _row(payload["horizons"], "15m")
    assert fixed_15m["avg_gross_return_pct"] == 0.0
    assert fixed_15m["avg_net_return_pct"] == -0.16


def test_hold_duration_replay_reports_pattern_supported_rejected_signals():
    service = HoldDurationReplayService(FakeRepo(), HoldDurationReplayConfig(cost_bps=0.0))

    payload = service.report("2026-06-30", lookback_days=0)

    pattern = payload["pattern_gate_counterfactual"]
    assert pattern["non_passing_rows"] == 2
    assert pattern["pattern_buy_supported_rows"] == 1
    assert pattern["pattern_avoid_supported_rows"] == 1

    buy_15m = _row(pattern["buy_supported_horizons"], "15m")
    avoid_15m = _row(pattern["avoid_supported_horizons"], "15m")
    assert buy_15m["avg_net_return_pct"] == 1.0
    assert buy_15m["ev_hit_rate_pct"] == 100.0
    assert avoid_15m["avg_net_return_pct"] == -1.0
    assert avoid_15m["negative_rate_pct"] == 100.0


def test_hold_duration_replay_applies_authority_gate_to_pattern_supported_rows():
    service = HoldDurationReplayService(
        PatternGateRepo(),
        HoldDurationReplayConfig(cost_bps=16.0, gate_permutations=50),
    )

    payload = service.report("2026-06-30", lookback_days=0)

    pattern = payload["pattern_gate_counterfactual"]
    gate_15m = _row(pattern["authority_gate_horizons"], "15m")
    assert pattern["authority_screen_verdict"] == "screen_pass_but_not_authority_ready"
    assert set(pattern["authority_screen_pass_horizons"]) == {"15m", "eod"}
    assert "no_precommitted_primary_horizon" in pattern["authority_screen_limitations"]
    decile = gate_15m["decile_test"]
    assert decile["sample_fingerprint"]
    assert decile["block_count"] == 1
    assert decile["null_exceedances"] is not None
    assert decile["null_lift_std"] is not None
    assert decile["permutation_seed_salt"] == "15m:long_opportunity_score:100"
    assert gate_15m["net_ev_pass"] is True
    assert gate_15m["decile_lift_pass"] is True
    assert gate_15m["p_value_pass"] is True
    assert gate_15m["verdict"] == "passes_research_bar"
    assert gate_15m["decile_test"]["success_definition"] == "net_return_pct >= 0.25"


if __name__ == "__main__":
    test_hold_duration_replay_computes_fixed_horizon_and_policy_stats()
    test_hold_duration_replay_applies_round_trip_cost_bps()
    test_hold_duration_replay_uses_realistic_default_cost_bps()
    test_hold_duration_replay_reports_pattern_supported_rejected_signals()
    test_hold_duration_replay_applies_authority_gate_to_pattern_supported_rows()
    print("[OK] hold-duration replay service tests passed")
