#!/usr/bin/env python3
"""Tests for ML lifecycle, feature, label, and serving contracts."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SRC = ROOT / "src"
SCRIPTS = ROOT / "scripts"
for path in (SCRIPTS, ROOT, SRC):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from ml_platform.lifecycle import (  # noqa: E402
    PAPER_LEARNING_CONFOUNDER_FIELDS,
    REQUIRED_PROMOTION_METRICS,
    assess_lifecycle_evidence,
    lifecycle_contract_summary,
)
from ml_platform.serving import (  # noqa: E402
    CachedPredictionProvider,
    CachedPredictionProviderConfig,
    PredictionView,
    serving_contract_summary,
)
from trading_bot.learning.features import feature_registry_summary  # noqa: E402
from trading_bot.learning.labels import authority_for_label, label_hierarchy_summary  # noqa: E402


def test_lifecycle_blocks_simple_split_and_missing_metrics():
    evidence = {
        "dataset_manifest": {"ready": True},
        "manifest": {"ready": True},
        "feature_parity": {"ready": True},
        "purged_walk_forward": {"ready": True},
        "calibration_report": {"ready": True},
        "replay_decision_delta": {"ready": True},
        "cost_slippage_report": {"ready": True},
        "promotion_assessment": {"ready": True},
        "registry_write": {"ready": True},
    }
    assessment = assess_lifecycle_evidence(
        evidence,
        target_stage="candidate_registration",
        validation_method="chronological_80_20_observe_only",
        metrics={},
    )
    assert assessment.ready is False
    assert "validation:simple_split_not_promotion_eligible" in assessment.blockers
    assert len(assessment.missing_metrics) == len(REQUIRED_PROMOTION_METRICS)


def test_feature_registry_has_point_in_time_and_authority_metadata():
    payload = feature_registry_summary()
    assert payload["feature_count"] >= 8
    for row in payload["features"]:
        assert row["point_in_time_cutoff"]
        assert row["staleness_rule"]
        assert row["authority_eligibility"]


def test_label_hierarchy_caps_proxy_label_authority():
    payload = label_hierarchy_summary()
    assert len(payload["tiers"]) == 5
    assert authority_for_label("triple_barrier_label") == "observe_only_ranking"
    assert authority_for_label("realized_pnl") == "narrow_block_candidate_after_full_lifecycle"


class _FailingProvider:
    latency_budget_ms = 25
    timeout_ms = 50
    fail_open = True

    def get_prediction(self, market_date: str, symbol: str):
        raise RuntimeError("source unavailable")


class _StaticProvider:
    latency_budget_ms = 25
    timeout_ms = 50
    fail_open = True

    def __init__(self):
        self.calls = 0

    def get_prediction(self, market_date: str, symbol: str):
        self.calls += 1
        return PredictionView(
            market_date=market_date,
            symbol=symbol,
            prediction_score=55.0,
            confidence="medium",
            sample_size=30,
            trend_label="up",
            timing_score=0.4,
            reason="test",
        )


def test_cached_prediction_provider_fails_open_and_caches():
    failing = CachedPredictionProvider(_FailingProvider())
    assert failing.get_prediction("2026-06-08", "AAPL") is None

    source = _StaticProvider()
    cached = CachedPredictionProvider(
        source,
        config=CachedPredictionProviderConfig(ttl_seconds=60, model_id="m1", model_version="v1"),
    )
    first = cached.get_prediction("2026-06-08", "AAPL")
    second = cached.get_prediction("2026-06-08", "AAPL")
    assert first is not None
    assert second is not None
    assert first.cache_status == "refresh"
    assert second.cache_status == "hit"
    assert second.model_id == "m1"
    assert source.calls == 1


def test_lifecycle_summary_includes_paper_confounder_controls():
    payload = lifecycle_contract_summary()
    assert "purged_walk_forward_v1" in payload["promotion_eligible_validation_methods"]
    assert "baseline_decision_without_override" in PAPER_LEARNING_CONFOUNDER_FIELDS
    assert "approval_source_classes" in payload


def test_serving_contract_summary_is_fail_open():
    payload = serving_contract_summary()
    assert payload["fail_open"] is True
    assert payload["cache"] == "CachedPredictionProvider"


if __name__ == "__main__":
    tests = [
        test_lifecycle_blocks_simple_split_and_missing_metrics,
        test_feature_registry_has_point_in_time_and_authority_metadata,
        test_label_hierarchy_caps_proxy_label_authority,
        test_cached_prediction_provider_fails_open_and_caches,
        test_lifecycle_summary_includes_paper_confounder_controls,
        test_serving_contract_summary_is_fail_open,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} ML lifecycle contract tests passed.")
