#!/usr/bin/env python3
"""Tests for async AI pipeline architecture contract."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.async_ai_pipeline_architecture_service import async_pipeline_contract


def test_async_pipeline_contract_defines_storage_queue_and_guardrails():
    contract = async_pipeline_contract()

    assert contract["runtime_effect"] == "architecture_contract_no_background_worker_started"
    assert "alpaca_websocket_ingest" in contract["flow"]
    assert "create_hypertable" in contract["storage"]["timescale_schema_sql"]
    assert contract["task_queue"]["preferred"] == "celery_redis"
    assert contract["guardrails"]["order_path_no_network_ml_calls"] is True


def main():
    tests = [test_async_pipeline_contract_defines_storage_queue_and_guardrails]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} async AI pipeline architecture tests passed.")


if __name__ == "__main__":
    main()
