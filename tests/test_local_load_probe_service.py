#!/usr/bin/env python3
"""Tests for diagnostic-only local load probes."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.local_load_probe_service import (  # noqa: E402
    LoadProbeConfig,
    run_local_webhook_load_probe,
)


def test_local_webhook_load_probe_routes_all_requests():
    payload = run_local_webhook_load_probe(
        LoadProbeConfig(requests=8, concurrency=2, symbol="AAPL", action="buy")
    )

    assert payload["runtime_effect"] == "diagnostic_only_no_order_submission"
    assert payload["passed"] is True
    assert payload["ok_count"] == 8
    assert payload["failed_count"] == 0
    assert payload["callbacks"]["recorded"] == 8
    assert payload["callbacks"]["submitted"] == 8


def test_local_webhook_load_probe_clamps_concurrency_to_request_count():
    payload = run_local_webhook_load_probe(
        LoadProbeConfig(requests=3, concurrency=20, symbol="AAPL", action="buy")
    )

    assert payload["concurrency"] == 3
    assert payload["passed"] is True


def main():
    tests = [
        test_local_webhook_load_probe_routes_all_requests,
        test_local_webhook_load_probe_clamps_concurrency_to_request_count,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print(f"\nAll {len(tests)} local load probe tests passed.")


if __name__ == "__main__":
    main()
