#!/usr/bin/env python3
"""Tests for advanced alpha readiness scoring."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.advanced_alpha_readiness_service import (  # noqa: E402
    build_advanced_alpha_readiness_payload,
)


def _summary(rows: int = 600) -> dict:
    return {
        "rows": rows,
        "rows_with_forward_outcome": rows,
        "rows_with_order_flow": int(rows * 0.9),
        "rows_with_microstructure_context": int(rows * 0.85),
        "rows_with_fractional_memory": int(rows * 0.9),
        "triple_barriers": [{"triple_barrier_label": 1, "rows": rows}],
        "trend_scans": [{"trend_scan_label": 1, "rows": rows}],
        "cvd_divergences": [{"cvd_divergence_label": "bullish_absorption", "rows": rows}],
    }


def test_advanced_alpha_readiness_scores_integrated_bar_features():
    payload = build_advanced_alpha_readiness_payload(
        target_date="2026-06-04",
        db_path="/tmp/unused.db",
        env={
            "POLYGON_API_KEY": "x",
            "ALPACA_API_KEY": "a",
            "ALPACA_SECRET_KEY": "s",
        },
        bar_summary=_summary(),
    )
    data = payload.to_dict()
    by_family = {row["feature_family"]: row for row in data["items"]}

    assert data["report_version"] == "advanced_alpha_readiness_v1"
    assert data["runtime_effect"] == "readiness_only_no_live_authority"
    assert data["summary"]["authority_ready"] is False
    assert by_family["bar_order_flow_proxy"]["readiness_pct"] >= 85
    assert by_family["fractional_memory_trend_scan"]["readiness_pct"] >= 85
    assert by_family["true_trade_level_vpin"]["status"] == "not_ready"
    assert "schema_integrated" in by_family["true_trade_level_vpin"]["failed"]
    assert by_family["volume_clock_vpin"]["status"] == "not_ready"
    assert "volume_clock_enabled" in by_family["volume_clock_vpin"]["failed"]
    assert by_family["liquidity_stress_indicator"]["status"] == "partially_integrated"
    assert "lsi_feature_enabled" in by_family["liquidity_stress_indicator"]["failed"]
    assert data["summary"]["microstructure_coverage_rate"] == 85.0


def test_advanced_alpha_readiness_reports_external_feed_gaps():
    payload = build_advanced_alpha_readiness_payload(
        target_date="2026-06-04",
        db_path="/tmp/unused.db",
        env={},
        bar_summary=_summary(rows=0),
    )
    by_family = {row.feature_family: row for row in payload.items}

    assert by_family["etf_component_lead_lag"].status == "not_ready"
    assert "symbol_to_reference_mapping_configured" in by_family["etf_component_lead_lag"].failed
    assert by_family["options_skew_flow"].status == "not_ready"
    assert "options_feed_available" in by_family["options_skew_flow"].failed
    assert by_family["asymmetric_loss_model_comparison"].readiness_pct < 60


def main():
    tests = [
        test_advanced_alpha_readiness_scores_integrated_bar_features,
        test_advanced_alpha_readiness_reports_external_feed_gaps,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} advanced alpha readiness tests passed.")


if __name__ == "__main__":
    main()
