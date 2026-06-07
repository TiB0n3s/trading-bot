#!/usr/bin/env python3
"""Tests for observe-only historical-bar model intelligence summaries."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.historical_bar_model_intelligence_service import (  # noqa: E402
    HISTORICAL_BAR_MODEL_INTELLIGENCE_VERSION,
    build_historical_bar_model_intelligence,
)


def _write_diag(
    path: Path,
    *,
    label: str,
    accuracy: float,
    generated_at: str,
    rows_loaded: int = 5900,
    symbol_count: int = 59,
) -> None:
    payload = {
        "report_version": "historical_bar_observe_training_v1",
        "runtime_effect": "observe_only_no_live_authority",
        "model_id": f"historical_bar_{label}_{generated_at}",
        "label_target": label,
        "rows_loaded": rows_loaded,
        "symbol_count": symbol_count,
        "generated_at": generated_at,
        "label_counts": {"-1": 2500, "0": 50, "1": 2450},
        "training": {
            "trained": True,
            "sample_size": rows_loaded,
            "accuracy": accuracy,
            "provider": "sklearn_random_forest",
        },
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_historical_bar_model_intelligence_reports_observe_only_ready_labels():
    with tempfile.TemporaryDirectory() as tmp:
        candidate_dir = Path(tmp)
        _write_diag(
            candidate_dir / "historical_bar_triple_barrier_label_old.diagnostic.json",
            label="triple_barrier_label",
            accuracy=0.51,
            generated_at="2026-06-06T00:00:00+00:00",
        )
        _write_diag(
            candidate_dir / "historical_bar_triple_barrier_label_new.diagnostic.json",
            label="triple_barrier_label",
            accuracy=0.76,
            generated_at="2026-06-07T00:00:00+00:00",
        )
        _write_diag(
            candidate_dir / "historical_bar_trend_scan_label_new.diagnostic.json",
            label="trend_scan_label",
            accuracy=0.83,
            generated_at="2026-06-07T00:10:00+00:00",
        )

        payload = build_historical_bar_model_intelligence(
            candidate_dir=candidate_dir,
            min_rows=5000,
            min_symbols=20,
            min_accuracy=0.50,
        )

    assert payload["version"] == HISTORICAL_BAR_MODEL_INTELLIGENCE_VERSION
    assert payload["runtime_effect"] == "observe_only_no_live_authority"
    assert payload["authority"] == "observe_only_report_only_no_order_sizing_or_gate_authority"
    assert payload["status"] == "observe_only_ready"
    assert payload["diagnostics_found"] == 3
    assert payload["labels_assessed"] == 2
    assert payload["ready_label_count"] == 2
    assert payload["accuracy_min"] == 0.76
    assert payload["accuracy_max"] == 0.83
    assert payload["guardrails"]["can_block_trades"] is False
    assert payload["guardrails"]["can_size_orders"] is False
    assert payload["guardrails"]["can_submit_orders"] is False
    labels = {item["label_target"]: item for item in payload["labels"]}
    assert labels["triple_barrier_label"]["accuracy"] == 0.76
    assert labels["triple_barrier_label"]["positive_label_rate"] == 0.49
    assert labels["trend_scan_label"]["status"] == "observe_only_candidate_ready"


def test_historical_bar_model_intelligence_marks_failed_thresholds():
    with tempfile.TemporaryDirectory() as tmp:
        candidate_dir = Path(tmp)
        _write_diag(
            candidate_dir / "historical_bar_triple_barrier_label_new.diagnostic.json",
            label="triple_barrier_label",
            accuracy=0.42,
            generated_at="2026-06-07T00:00:00+00:00",
            rows_loaded=100,
            symbol_count=2,
        )

        payload = build_historical_bar_model_intelligence(
            candidate_dir=candidate_dir,
            min_rows=5000,
            min_symbols=20,
            min_accuracy=0.50,
        )

    assert payload["status"] == "not_ready"
    label = payload["labels"][0]
    assert label["status"] == "not_ready"
    assert "rows_loaded:100<5000" in label["failed_thresholds"]
    assert "symbol_count:2<20" in label["failed_thresholds"]
    assert "accuracy:0.4200<0.5000" in label["failed_thresholds"]


if __name__ == "__main__":
    test_historical_bar_model_intelligence_reports_observe_only_ready_labels()
    print("[OK] test_historical_bar_model_intelligence_reports_observe_only_ready_labels")
    test_historical_bar_model_intelligence_marks_failed_thresholds()
    print("[OK] test_historical_bar_model_intelligence_marks_failed_thresholds")
