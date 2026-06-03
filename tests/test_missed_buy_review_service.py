"""Tests for missed-buy review diagnostics."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.missed_buy_review_service import build_missed_buy_review_payload


def test_missed_buy_review_counts_only_non_taken_forward_winners():
    payload = build_missed_buy_review_payload(
        [
            {
                "candidate_ts": "2026-06-03T10:00:00",
                "symbol": "AAPL",
                "candidate_status": "scored_not_taken",
                "score": 74,
                "threshold": 80,
                "threshold_distance": -6,
                "reason": "negative_session_downtrend;below_vwap;setup_avoid",
                "setup_label": "avoid",
                "candidate_json": (
                    '{"candidate":{"symbol_pattern":"efi_pvt_reclaim",'
                    '"ml_prediction_bucket":"high_55_plus"},'
                    '"forward_mfe_pct":2.4,"forward_return_pct":1.2,'
                    '"forward_mae_pct":-0.2}'
                ),
            },
            {
                "candidate_ts": "2026-06-03T10:05:00",
                "symbol": "MSFT",
                "candidate_status": "scored_not_taken",
                "score": 55,
                "reason": "mom_strong_decel;setup_score<=20",
                "setup_label": "watch",
                "candidate_json": '{"forward_mfe_pct":0.2,"forward_return_pct":-0.5}',
            },
            {
                "candidate_ts": "2026-06-03T10:10:00",
                "symbol": "NVDA",
                "candidate_status": "taken",
                "score": 90,
                "reason": "approved",
                "candidate_json": '{"forward_mfe_pct":3.0,"forward_return_pct":2.0}',
            },
            {
                "candidate_ts": "2026-06-03T10:15:00",
                "symbol": "TSLA",
                "candidate_status": "near_threshold",
                "score": 78,
                "reason": "strategy_memory_caution_setup_below_min",
                "candidate_json": "{}",
            },
        ],
        min_mfe_pct=0.8,
    )

    assert payload.summary["report_version"] == "missed_buy_review_v1"
    assert payload.summary["runtime_effect"] == "diagnostic_only_no_live_authority"
    assert payload.summary["authority_ready"] is False
    assert payload.summary["candidate_rows"] == 4
    assert payload.summary["rows_with_forward_outcome"] == 3
    assert payload.summary["non_taken_with_forward_outcome"] == 2
    assert payload.summary["missed_good_candidates"] == 1
    assert payload.summary["high_quality_missed_candidates"] == 1
    assert payload.summary["correctly_avoided_or_bad_candidates"] == 1
    assert payload.top_missed[0]["symbol"] == "AAPL"
    assert payload.top_missed[0]["quality"] == "high_quality_missed"
    reasons = {row["key"]: row["count"] for row in payload.reason_token_counts}
    assert reasons["negative_session_downtrend"] == 1
    assert reasons["below_vwap"] == 1
    assert reasons["setup_avoid"] == 1
    assert reasons["ml_prediction_high_55_plus"] == 1
    assert payload.symbol_counts[0] == {"key": "AAPL", "count": 1}
    assert any("candidate-outcome-backfill" in action for action in payload.learning_actions)


if __name__ == "__main__":
    test_missed_buy_review_counts_only_non_taken_forward_winners()
    print("missed buy review service tests passed")
