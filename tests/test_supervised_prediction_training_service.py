#!/usr/bin/env python3
"""Tests for supervised prediction training scaffold."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.optional_dependency_service import optional_dependency_status
from services.supervised_prediction_training_service import (
    asymmetric_false_positive_logistic_objective,
    train_quant_model_suite,
    train_supervised_prediction_model,
)


def _rows(n=60):
    rows = []
    for i in range(n):
        rows.append(
            {
                "ret_1m": i % 3,
                "ret_5m": i % 5,
                "ret_15m": i % 7,
                "range_pos_15m": 0.5,
                "distance_from_vwap": 0.1,
                "volume_ratio_5m": 1.0,
                "relative_strength_5m": 0.2,
                "spread_pct": 0.01,
                "setup_score": 60,
                "ema_12": 100.5 + i * 0.01,
                "ema_26": 100.1 + i * 0.01,
                "macd": 0.4,
                "macd_signal": 0.35,
                "rsi_14": 62.0,
                "webull_rsi_14": 61.5,
                "webull_rsi_bearish_divergence": 0,
                "candle_body_pct": 0.6,
                "upper_wick_pct": 0.1,
                "lower_wick_pct": 0.3,
                "upper_lower_wick_ratio": 0.333,
                "close_location": 0.8,
                "range_atr_ratio": 1.2,
                "atr_20_pct": 0.4,
                "volume_ratio_20": 1.5,
                "pressure_return_3": 0.2,
                "pressure_return_8": 0.4,
                "volume_weighted_pressure_3": 0.3,
                "volume_delta": 1000 if i % 2 == 0 else -800,
                "institutional_volume_delta": 1000 if i % 3 == 0 else 0,
                "cumulative_volume_delta": i * 100,
                "cvd_price_corr_20": 0.25,
                "vpin_toxicity_20": 0.72,
                "fractional_diff_close_045": 12.0 + i * 0.01,
                "fractional_diff_zscore_20": 0.8,
                "trend_scan_label": 1 if i % 3 == 0 else (-1 if i % 3 == 1 else 0),
                "trend_scan_tstat": 2.6 if i % 3 == 0 else -2.2,
                "trend_scan_return_pct": 0.8 if i % 3 == 0 else -0.6,
                "day_of_month": 2,
                "week_of_month": 1,
                "month_end_proximity_days": 28,
                "monday_volatility_flag": 0,
                "friday_rebalance_flag": 1,
                "prior_session_return_pct": 0.4,
                "prior_5_session_return_pct": 1.8,
                "pattern_score": 72,
                "long_opportunity_score": 80,
                "sell_opportunity_score": 20,
                "triple_barrier_label": 1 if i % 3 == 0 else (-1 if i % 3 == 1 else 0),
                "ret_fwd_15m": 0.2 if i % 2 == 0 else -0.1,
            }
        )
    return rows


def test_train_supervised_prediction_model_uses_baseline_without_required_deps():
    result = train_supervised_prediction_model(rows=_rows(), min_samples=40).to_dict()

    assert result["trained"] is True
    assert result["sample_size"] == 60
    assert result["baseline_positive_rate"] == 0.5
    assert result["runtime_effect"] == "observe_only_no_live_authority"
    assert "artifact_path" in result
    assert "candle_body_pct" in result["feature_columns"]
    assert "ema_12" in result["feature_columns"]
    assert "macd" in result["feature_columns"]
    assert "rsi_14" in result["feature_columns"]
    assert "webull_rsi_14" in result["feature_columns"]
    assert "webull_rsi_bearish_divergence" in result["feature_columns"]
    assert "prior_session_return_pct" in result["feature_columns"]
    assert "prior_5_session_return_pct" in result["feature_columns"]
    assert "friday_rebalance_flag" in result["feature_columns"]


def test_train_supervised_prediction_model_blocks_small_samples():
    result = train_supervised_prediction_model(rows=_rows(5), min_samples=40).to_dict()

    assert result["trained"] is False
    assert "insufficient labeled rows" in result["reason"]


def test_train_quant_model_suite_compares_available_observe_only_models():
    with tempfile.TemporaryDirectory() as tmp:
        result = train_quant_model_suite(
            rows=_rows(80),
            min_samples=40,
            artifact_dir=Path(tmp),
            model_id_prefix="test_suite",
        ).to_dict()

    providers = {row["provider"] for row in result["models"]}
    assert result["version"] == "quant_model_suite_v3"
    assert result["runtime_effect"] == "observe_only_no_live_authority"
    assert result["sample_size"] == 80
    assert "chronological_positive_rate_baseline" in providers
    deps = optional_dependency_status()["packages"]
    if deps.get("sklearn", {}).get("available"):
        assert "sklearn_random_forest" in providers
    if deps.get("xgboost", {}).get("available"):
        assert "xgboost_asymmetric_false_positive" in providers
    assert result["best_model"] is None or result["best_model"]["provider"] in providers
    assert all(
        row["runtime_effect"] == "observe_only_no_live_authority" for row in result["models"]
    )


def test_asymmetric_objective_penalizes_false_positive_pressure():
    class FakeDTrain:
        @staticmethod
        def get_label():
            return [0, 1]

    grad, hess = asymmetric_false_positive_logistic_objective(
        [2.0, -2.0],
        FakeDTrain(),
        false_positive_penalty=10.0,
    )

    assert grad[0] > abs(grad[1])
    assert hess[0] > hess[1]


def test_train_supervised_prediction_model_can_use_triple_barrier_target():
    result = train_supervised_prediction_model(
        rows=_rows(90),
        horizon="triple_barrier",
        min_samples=40,
    ).to_dict()

    assert result["trained"] is True
    assert result["sample_size"] == 90
    assert "triple_barrier" in result["reason"] or result["provider"]
    assert result["runtime_effect"] == "observe_only_no_live_authority"


def test_train_supervised_prediction_model_can_use_trend_scan_target():
    result = train_supervised_prediction_model(
        rows=_rows(90),
        horizon="trend_scan",
        min_samples=40,
    ).to_dict()

    assert result["trained"] is True
    assert result["sample_size"] == 90
    assert "trend_scan_tstat" not in result["feature_columns"]
    assert "trend_scan_return_pct" not in result["feature_columns"]
    assert result["runtime_effect"] == "observe_only_no_live_authority"


def main():
    tests = [
        test_train_supervised_prediction_model_uses_baseline_without_required_deps,
        test_train_supervised_prediction_model_blocks_small_samples,
        test_train_quant_model_suite_compares_available_observe_only_models,
        test_asymmetric_objective_penalizes_false_positive_pressure,
        test_train_supervised_prediction_model_can_use_triple_barrier_target,
        test_train_supervised_prediction_model_can_use_trend_scan_target,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} supervised prediction training tests passed.")


if __name__ == "__main__":
    main()
