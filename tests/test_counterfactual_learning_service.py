#!/usr/bin/env python3
"""Tests for counterfactual false-negative veto-relaxation learning."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.counterfactual_learning_service import (  # noqa: E402
    enforce_veto_relaxation_guardrail,
    evaluate_counterfactual_veto_relaxation,
    relaxation_target,
    train_counterfactual_veto_relaxation_model,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy value, got {value!r}")


def _row(i: int, *, positive: bool) -> dict:
    base = {
        "symbol": "AAPL",
        "timestamp": f"2026-06-0{(i % 5) + 1}T14:{i % 60:02d}:00+00:00",
        "action": "buy",
        "signal_price": 100.0,
        "rejection_reason": "meta_label:veto",
        "max_favorable_60m": 1.2 if positive else 0.2,
        "max_adverse_60m": -0.2 if positive else -0.9,
        "canonical_intelligence_json": json.dumps(
            {
                "level_1_expert_ensemble": {"ensemble_probability": 0.61 if positive else 0.42},
                "level_2_meta_label": {
                    "success_probability": 63.0 if positive else 41.0,
                    "threshold": 0.65,
                },
            }
        ),
        "setup_score": 72 if positive else 35,
        "ret_1m": 0.05 if positive else -0.08,
        "ret_5m": 0.18 if positive else -0.22,
        "ret_15m": 0.25 if positive else -0.31,
        "range_pos_15m": 0.82 if positive else 0.22,
        "distance_from_vwap": 0.15 if positive else -0.7,
        "volume_ratio_5m": 1.8 if positive else 0.7,
        "relative_strength_5m": 0.4 if positive else -0.35,
        "spread_pct": 0.02 if positive else 0.18,
        "momentum_acceleration_pct": 0.12 if positive else -0.1,
        "volume_surge_ratio": 1.5 if positive else 0.6,
        "extension_from_recent_base_pct": 0.4 if positive else -0.5,
        "prior_session_return_pct": 0.7 if positive else -0.8,
        "candle_body_pct": 0.65 if positive else 0.2,
        "close_location": 0.88 if positive else 0.24,
        "range_atr_ratio": 1.1 if positive else 1.8,
        "atr_20_pct": 0.7 if positive else 1.6,
        "volume_ratio_20": 1.4 if positive else 0.8,
        "volume_weighted_pressure_3": 0.4 if positive else -0.3,
        "cvd_price_corr_20": 0.35 if positive else -0.2,
        "vpin_toxicity_20": 0.2 if positive else 0.8,
        "fractional_diff_zscore_20": 0.6 if positive else -0.4,
        "trend_scan_tstat": 2.2 if positive else -1.8,
        "pattern_score": 78 if positive else 30,
    }
    return base


def _rows() -> list[dict]:
    return [_row(i, positive=i % 2 == 0) for i in range(40)]


def test_relaxation_target_requires_profit_without_stopout():
    assert_equal(relaxation_target(_row(1, positive=True)), 1, "positive target")
    assert_equal(relaxation_target(_row(1, positive=False)), 0, "negative target")


def test_counterfactual_model_trains_and_scores_live_features():
    with tempfile.TemporaryDirectory() as tmp:
        artifact = Path(tmp) / "veto_relaxation_model.json"
        result = train_counterfactual_veto_relaxation_model(
            rows=_rows(),
            artifact_path=artifact,
            min_samples=20,
            min_positive=5,
        ).to_dict()
        assert_equal(result["trained"], True, "trained")
        assert_true(artifact.exists(), "artifact exists")

        scored = evaluate_counterfactual_veto_relaxation(
            account_state={
                "historical_bar_paper_strategy": {"master_confidence_score": 63.0},
                "level_1_expert_ensemble": {"ensemble_probability": 0.61},
                "level_2_meta_label": {"threshold": 0.65},
                **_row(100, positive=True),
            },
            artifact_path=artifact,
        )
        assert_equal(scored["status"], "active", "status")
        assert_true(scored["p_unveto"] >= 0.75, "p_unveto")
        assert_true(scored["threshold_relaxation_pct"] > 0, "relaxation")


def test_guardrail_deletes_weak_overruled_model():
    with tempfile.TemporaryDirectory() as tmp:
        artifact = Path(tmp) / "veto_relaxation_model.json"
        artifact.write_text("{}")
        rows = []
        for i in range(6):
            row = _row(i, positive=False)
            row["rejection_reason"] = "counterfactual_veto_relaxation:overruled"
            rows.append(row)
        result = enforce_veto_relaxation_guardrail(rows, artifact_path=artifact)
        assert_equal(result["disabled_model"], True, "disabled")
        assert_equal(artifact.exists(), False, "artifact deleted")


def main():
    tests = [
        test_relaxation_target_requires_profit_without_stopout,
        test_counterfactual_model_trains_and_scores_live_features,
        test_guardrail_deletes_weak_overruled_model,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} counterfactual learning tests passed.")


if __name__ == "__main__":
    main()
