#!/usr/bin/env python3
"""Tests for supervised prediction training scaffold."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.supervised_prediction_training_service import train_supervised_prediction_model


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


def test_train_supervised_prediction_model_blocks_small_samples():
    result = train_supervised_prediction_model(rows=_rows(5), min_samples=40).to_dict()

    assert result["trained"] is False
    assert "insufficient labeled rows" in result["reason"]


def main():
    tests = [
        test_train_supervised_prediction_model_uses_baseline_without_required_deps,
        test_train_supervised_prediction_model_blocks_small_samples,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} supervised prediction training tests passed.")


if __name__ == "__main__":
    main()
