#!/usr/bin/env python3
"""Tests for observe-only runtime regime observation context."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.regime_observation_service import RegimeObservationService


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def assert_true(value, label):
    if not value:
        raise AssertionError(f"{label}: expected truthy value")


def test_observe_returns_regime_and_routing_payload_without_authority():
    with tempfile.TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        closes = [100 + idx * 0.2 for idx in range(60)]
        service = RegimeObservationService(
            base_dir=base_dir,
            fetch_closes=lambda limit: closes[-limit:],
            save_state=True,
        )

        payload = service.observe(closes_limit=60)

        assert_equal(payload["runtime_effect"], "observe_only_no_order_authority", "runtime")
        assert_true(payload["regime_observation"]["regime_label"], "regime label")
        assert_true(payload["regime_routing_decision"]["active_model_slot"], "model slot")
        assert_equal(
            payload["regime_routing_decision"]["runtime_effect"],
            "observe_only_no_order_authority",
            "routing runtime",
        )
        assert_true((base_dir / "runtime_state" / "regime_state.json").exists(), "state persisted")


def main():
    tests = [test_observe_returns_regime_and_routing_payload_without_authority]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} regime observation service tests passed.")


if __name__ == "__main__":
    main()
