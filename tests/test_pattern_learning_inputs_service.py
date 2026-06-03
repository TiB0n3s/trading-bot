"""Tests for pattern-learning input coverage summaries."""

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.pattern_learning_inputs_service import build_pattern_learning_inputs_payload


def test_pattern_learning_inputs_classifies_trade_and_candidate_coverage():
    payload = build_pattern_learning_inputs_payload(
        [
            {
                "symbol": "AAPL",
                "realized_pnl_pct": 0.8,
                "mfe_pct": 1.2,
                "capture_ratio": 0.67,
                "setup_policy_action": "neutral",
                "ml_prediction_bucket": "high_55_plus",
                "session_trend_label": "strong_uptrend",
                "buy_opportunity_recommendation": "strong_buy_candidate",
            },
            {
                "symbol": "MSFT",
                "realized_pnl_pct": -0.2,
                "mfe_pct": 0.55,
                "capture_ratio": -0.36,
                "setup_policy_action": "watch",
                "ml_prediction_bucket": "weak_below_45",
                "session_trend_label": "developing_uptrend",
                "buy_opportunity_recommendation": "watch",
            },
        ],
        [
            {
                "symbol": "NVDA",
                "candidate_status": "near_threshold",
                "candidate_json": '{"forward_mfe_pct": 1.4, "forward_return_pct": 0.7, "symbol_pattern": "trend_continuation_with_participation"}',
            },
            {
                "symbol": "TSLA",
                "candidate_status": "scored_not_taken",
                "candidate_json": "{}",
            },
        ],
    )

    assert payload.summary["report_version"] == "pattern_learning_inputs_v1"
    assert payload.summary["runtime_effect"] == "diagnostic_only_no_live_authority"
    assert payload.summary["authority_ready"] is False
    assert payload.summary["matched_trades"] == 2
    assert payload.summary["fully_integrated_pattern_outcome_rows"] == 2
    assert payload.summary["quality_counts"]["good_buy_good_sell"] == 1
    assert payload.summary["quality_counts"]["good_buy_poor_sell_or_late_exit"] == 1
    assert payload.candidate_label_coverage["rows"] == 2
    assert payload.candidate_label_coverage["rows_with_forward_outcome"] == 1
    assert payload.candidate_label_coverage["proven_good"] == 1
    assert payload.candidate_label_coverage["top_missed_by_mfe"][0]["symbol"] == "NVDA"


if __name__ == "__main__":
    test_pattern_learning_inputs_classifies_trade_and_candidate_coverage()
    print("pattern learning input service tests passed")
