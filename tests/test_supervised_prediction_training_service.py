#!/usr/bin/env python3
"""Tests for supervised prediction training scaffold."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.supervised_prediction_training_service import (
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
    assert "sklearn_random_forest" in providers
    assert result["best_model"] is None or result["best_model"]["provider"] in providers
    assert all(row["runtime_effect"] == "observe_only_no_live_authority" for row in result["models"])


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
    assert "trend_scan_tstat" in result["feature_columns"]
    assert result["runtime_effect"] == "observe_only_no_live_authority"


def main():
    tests = [
        test_train_supervised_prediction_model_uses_baseline_without_required_deps,
        test_train_supervised_prediction_model_blocks_small_samples,
        test_train_quant_model_suite_compares_available_observe_only_models,
        test_train_supervised_prediction_model_can_use_triple_barrier_target,
        test_train_supervised_prediction_model_can_use_trend_scan_target,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} supervised prediction training tests passed.")


if __name__ == "__main__":
    main()
