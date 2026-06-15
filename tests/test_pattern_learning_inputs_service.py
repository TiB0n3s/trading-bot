"""Tests for pattern-learning input coverage summaries."""

import sys
from pathlib import Path

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
                "candidate_json": (
                    '{"forward_mfe_pct": 1.4, "forward_return_pct": 0.7, '
                    '"candidate": {"symbol_pattern": "trend_continuation_with_participation", '
                    '"confluence_score": 24.0, "conviction_score": 24.0, '
                    '"probability_pct": 64.5, '
                    '"probability_source": "daily_symbol_predictions:probability_of_profit"}}'
                ),
            },
            {
                "symbol": "TSLA",
                "candidate_status": "scored_not_taken",
                "candidate_json": (
                    '{"candidate": {"confluence_score": 18.0, '
                    '"conviction_score": 18.0, "probability_pct": 81.0, '
                    '"probability_source": "daily_symbol_predictions:probability_of_order"}}'
                ),
            },
        ],
        [
            {
                "symbol": "AAPL",
                "bar_timestamp": "2026-05-30T10:10:00",
                "timeframe": "5m",
                "pattern_label": "efi_pvt_breakout_confirmation",
                "opportunity_action": "long_candidate",
                "opportunity_quality": "best_buy_window",
                "long_opportunity_score": 82.5,
                "sell_opportunity_score": 10.0,
                "forward_return_pct": 0.9,
                "forward_mfe_pct": 1.6,
                "forward_mae_pct": -0.1,
                "triple_barrier_label": 1,
                "triple_barrier_reason": "profit_target_first",
                "triple_barrier_bars_to_event": 3,
                "trend_scan_label": 1,
                "trend_scan_reason": "positive_structural_trend",
                "trend_scan_tstat": 3.1,
                "trend_scan_bars": 8,
                "cvd_divergence_label": "bullish_absorption",
                "cvd_price_corr_20": 0.4,
                "vpin_toxicity_20": 0.7,
                "fractional_diff_zscore_20": 1.2,
                "runtime_effect": "observe_only_pattern_learning_no_live_authority",
            },
            {
                "symbol": "AAPL",
                "bar_timestamp": "2026-05-30T11:20:00",
                "timeframe": "5m",
                "pattern_label": "efi_fading_pvt_flat",
                "opportunity_action": "sell_or_avoid_candidate",
                "opportunity_quality": "risk_window",
                "long_opportunity_score": 12.0,
                "sell_opportunity_score": 75.0,
                "forward_return_pct": -0.4,
                "forward_mfe_pct": 0.1,
                "forward_mae_pct": -0.8,
                "triple_barrier_label": -1,
                "triple_barrier_reason": "stop_loss_first",
                "triple_barrier_bars_to_event": 2,
                "trend_scan_label": -1,
                "trend_scan_reason": "negative_structural_trend",
                "trend_scan_tstat": -2.4,
                "trend_scan_bars": 6,
                "cvd_divergence_label": "bearish_distribution",
                "cvd_price_corr_20": -0.2,
                "vpin_toxicity_20": 0.8,
                "fractional_diff_zscore_20": -1.0,
                "runtime_effect": "observe_only_pattern_learning_no_live_authority",
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
    assert payload.candidate_label_coverage["rows_with_confluence_score"] == 2
    assert payload.candidate_label_coverage["rows_with_conviction_score"] == 2
    assert payload.candidate_label_coverage["rows_with_probability_pct"] == 2
    assert payload.candidate_label_coverage["avg_confluence_score"] == 21.0
    assert payload.candidate_label_coverage["avg_conviction_score"] == 21.0
    assert payload.candidate_label_coverage["confluence_score_buckets"]["23_plus"] == 1
    assert payload.candidate_label_coverage["conviction_score_buckets"]["15_to_19_99"] == 1
    assert payload.candidate_label_coverage["probability_buckets"]["62_to_79_99"] == 1
    assert payload.candidate_label_coverage["probability_buckets"]["80_plus"] == 1
    assert (
        payload.candidate_label_coverage["probability_source_counts"][
            "daily_symbol_predictions:probability_of_profit"
        ]
        == 1
    )
    assert payload.candidate_label_coverage["conviction_score_ready_rows"] == 1
    assert payload.candidate_label_coverage["conviction_probability_ready_rows"] == 2
    assert payload.candidate_label_coverage["conviction_candidate_rows"] == 1
    assert payload.candidate_label_coverage["conviction_candidate_rate"] == 0.5
    assert payload.candidate_label_coverage["top_missed_by_mfe"][0]["symbol"] == "NVDA"
    assert payload.candidate_label_coverage["top_missed_by_mfe"][0]["conviction_score"] == 24.0
    assert payload.candidate_label_coverage["top_missed_by_mfe"][0]["probability_pct"] == 64.5
    assert payload.summary["bar_pattern_rows"] == 2
    assert payload.summary["candidate_rows_with_confluence_score"] == 2
    assert payload.summary["candidate_rows_with_conviction_score"] == 2
    assert payload.summary["candidate_rows_with_probability_pct"] == 2
    assert payload.summary["conviction_candidate_rows"] == 1
    assert payload.summary["bar_pattern_rows_with_opportunity_label"] == 2
    assert payload.bar_pattern_evidence["rows_with_forward_outcome"] == 2
    assert payload.bar_pattern_evidence["opportunity_counts"]["long_candidate|best_buy_window"] == 1
    assert payload.bar_pattern_evidence["triple_barrier_counts"]["1|profit_target_first"] == 1
    assert payload.bar_pattern_evidence["triple_barrier_counts"]["-1|stop_loss_first"] == 1
    assert payload.bar_pattern_evidence["triple_barrier_expectancy"]
    assert payload.bar_pattern_evidence["trend_scan_counts"]["1|positive_structural_trend"] == 1
    assert payload.bar_pattern_evidence["trend_scan_expectancy"]
    assert payload.bar_pattern_evidence["cvd_divergence_counts"]["bullish_absorption"] == 1
    assert payload.bar_pattern_evidence["order_flow_coverage_rate"] == 1.0
    assert payload.bar_pattern_evidence["fractional_memory_coverage_rate"] == 1.0
    assert payload.bar_pattern_evidence["buy_window_rows_with_forward_return"] == 1
    assert payload.bar_pattern_evidence["buy_window_win_rate"] == 1.0
    assert payload.bar_pattern_evidence["buy_window_avg_forward_return_pct"] == 0.9
    assert payload.bar_pattern_evidence["buy_windows_with_positive_mfe"] == 1
    assert payload.bar_pattern_evidence["sell_avoid_rows_with_forward_return"] == 1
    assert payload.bar_pattern_evidence["sell_avoid_correct_direction_rate"] == 1.0
    assert payload.bar_pattern_evidence["sell_avoid_avg_forward_return_pct"] == -0.4
    assert payload.bar_pattern_evidence["top_buy_windows"][0]["symbol"] == "AAPL"
    assert payload.bar_pattern_evidence["top_sell_or_avoid_windows"][0]["symbol"] == "AAPL"


if __name__ == "__main__":
    test_pattern_learning_inputs_classifies_trade_and_candidate_coverage()
    print("pattern learning input service tests passed")
