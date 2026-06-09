#!/usr/bin/env python3
"""Tests for cross-layer model verification matrix."""

from __future__ import annotations

import json
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.cross_layer_verification_service import (  # noqa: E402
    build_cross_layer_verification_payload,
)


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy value, got {value!r}")


def _layered(
    *,
    score: float,
    threshold: float,
    instruction: str,
    final_instruction: str,
    final_size: float,
    requested_size: float = 1.0,
    unveto_status: str = "active",
    p_unveto: float | None = None,
    relaxation_pct: float = 0.0,
) -> dict:
    return {
        "version": "layered_model_decision_v1",
        "final_instruction": final_instruction,
        "level_0_regime": {
            "regime_label": "quiet_bull",
            "allow_new_longs": True,
            "size_modifier": 1.0,
        },
        "level_0_alternative_gates": {"decision": "pass"},
        "level_2_meta_label": {
            "instruction": instruction,
            "success_probability": score,
            "threshold": threshold,
            "counterfactual_veto_relaxation": {
                "status": unveto_status,
                "p_unveto": p_unveto,
                "threshold_relaxation_pct": relaxation_pct,
            },
        },
        "level_3_sizing": {
            "requested_size_pct": requested_size,
            "regime_adjusted_size_pct": requested_size,
            "final_size_pct": final_size,
        },
    }


def _row(idx: int, layered: dict, *, symbol: str = "AAPL") -> dict:
    return {
        "id": idx,
        "decision_time": f"2026-06-09T14:{idx:02d}:00+00:00",
        "symbol": symbol,
        "action": "buy",
        "approved": 1 if layered["final_instruction"] != "veto" else 0,
        "final_decision": layered["final_instruction"],
        "account_state_json": "{}",
        "canonical_intelligence_json": json.dumps({"layered_model_decision": layered}),
    }


def test_cross_layer_matrix_detects_marginal_approval_size_down():
    rows = [
        _row(
            1,
            _layered(
                score=0.662,
                threshold=0.65,
                instruction="pass",
                final_instruction="paper_approval",
                final_size=0.4,
            ),
        )
    ]
    payload = build_cross_layer_verification_payload(
        rows,
        target_date="2026-06-09",
        drift_artifact_path="/tmp/does-not-exist-cross-layer.json",
    ).to_dict()

    assert_equal(payload["summary"]["layered_rows"], 1, "layered rows")
    assert_equal(
        payload["veto_to_sizing_handshake"]["status"],
        "marginal_approvals_scaled_down",
        "handshake",
    )
    assert_equal(payload["warnings"], [], "warnings")


def test_cross_layer_matrix_reports_marginal_score_size_correlation():
    rows = [
        _row(
            1,
            _layered(
                score=0.652,
                threshold=0.65,
                instruction="pass",
                final_instruction="paper_approval",
                final_size=0.35,
            ),
        ),
        _row(
            2,
            _layered(
                score=0.675,
                threshold=0.65,
                instruction="pass",
                final_instruction="paper_approval",
                final_size=0.55,
            ),
        ),
        _row(
            3,
            _layered(
                score=0.698,
                threshold=0.65,
                instruction="pass",
                final_instruction="paper_approval",
                final_size=0.85,
            ),
        ),
    ]
    payload = build_cross_layer_verification_payload(
        rows,
        target_date="2026-06-09",
        drift_artifact_path="/tmp/does-not-exist-cross-layer.json",
    ).to_dict()

    translation = payload["marginal_risk_translation"]
    assert_equal(translation["status"], "correlation_available", "status")
    assert_true(translation["correlation"] > 0.90, "correlation")
    assert_true(translation["avg_allocation_multiplier"] < 0.70, "avg multiplier")


def test_cross_layer_matrix_detects_level0_level2_divergence():
    rows = [
        _row(
            1,
            _layered(
                score=0.40,
                threshold=0.65,
                instruction="veto",
                final_instruction="veto",
                final_size=0.0,
            ),
            symbol="AAPL",
        ),
        _row(
            2,
            _layered(
                score=0.42,
                threshold=0.65,
                instruction="veto",
                final_instruction="veto",
                final_size=0.0,
            ),
            symbol="MSFT",
        ),
        _row(
            3,
            _layered(
                score=0.44,
                threshold=0.65,
                instruction="veto",
                final_instruction="veto",
                final_size=0.0,
            ),
            symbol="NVDA",
        ),
    ]
    payload = build_cross_layer_verification_payload(
        rows,
        target_date="2026-06-09",
        drift_artifact_path="/tmp/does-not-exist-cross-layer.json",
    ).to_dict()

    anomaly = payload["cross_layer_anomaly"]
    assert_equal(
        anomaly["status"],
        "stable_level0_low_level2_confidence_cluster",
        "anomaly status",
    )
    assert_true(payload["warnings"], "warning")


def test_cross_layer_matrix_warns_when_severe_drift_does_not_disable_relaxation():
    with tempfile.TemporaryDirectory() as tmp:
        artifact = Path(tmp) / "concept_drift.json"
        artifact.write_text(json.dumps({"severe_drift": True, "max_psi": 0.31}))
        rows = [
            _row(
                1,
                _layered(
                    score=0.60,
                    threshold=0.65,
                    instruction="veto",
                    final_instruction="veto",
                    final_size=0.0,
                    p_unveto=0.81,
                    relaxation_pct=8.1,
                ),
            )
        ]
        payload = build_cross_layer_verification_payload(
            rows,
            target_date="2026-06-09",
            drift_artifact_path=artifact,
        ).to_dict()

    assert_equal(payload["drift_relaxation_symmetry"]["severe_drift"], True, "drift")
    assert_true(payload["warnings"], "warnings")
    assert_true(
        any("relaxation is active despite severe drift" in row for row in payload["warnings"]),
        "severe drift warning",
    )


def test_cross_layer_matrix_warns_on_missing_layered_payloads():
    payload = build_cross_layer_verification_payload(
        [
            {
                "id": 1,
                "decision_time": "2026-06-09T14:00:00+00:00",
                "symbol": "AAPL",
                "action": "buy",
                "account_state_json": "{}",
                "canonical_intelligence_json": "{}",
            }
        ],
        target_date="2026-06-09",
        drift_artifact_path="/tmp/does-not-exist-cross-layer.json",
    ).to_dict()

    assert_equal(payload["summary"]["layered_rows"], 0, "layered rows")
    assert_true(payload["warnings"], "coverage warning")


def main():
    tests = [
        test_cross_layer_matrix_detects_marginal_approval_size_down,
        test_cross_layer_matrix_reports_marginal_score_size_correlation,
        test_cross_layer_matrix_detects_level0_level2_divergence,
        test_cross_layer_matrix_warns_when_severe_drift_does_not_disable_relaxation,
        test_cross_layer_matrix_warns_on_missing_layered_payloads,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} cross-layer verification tests passed.")


if __name__ == "__main__":
    main()
