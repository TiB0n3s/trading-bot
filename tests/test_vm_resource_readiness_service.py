#!/usr/bin/env python3
"""Tests for VM resource readiness inventory."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.vm_resource_readiness_service import (  # noqa: E402
    RESOURCE_READINESS_VERSION,
    vm_resource_readiness,
)


def test_vm_resource_readiness_is_non_authoritative():
    payload = vm_resource_readiness(env={})

    assert payload["version"] == RESOURCE_READINESS_VERSION
    assert payload["runtime_effect"] == "readiness_only_no_live_authority"
    assert payload["total_count"] >= 5
    keys = {row["key"] for row in payload["resources"]}
    assert "sec_edgar_official_disclosures" in keys
    assert "polygon_market_data" in keys
    assert "duckdb_research_exports" in keys


def test_vm_resource_readiness_reports_missing_credentials():
    payload = vm_resource_readiness(env={"POLYGON_API_KEY": "x"})
    polygon = next(row for row in payload["resources"] if row["key"] == "polygon_market_data")
    sec = next(row for row in payload["resources"] if row["key"] == "sec_edgar_official_disclosures")

    assert "POLYGON_API_KEY" in polygon["env"]["present"]
    assert "SEC_EDGAR_USER_AGENT" in sec["env"]["missing"]
    assert polygon["runtime_effect"] == "observe_only_until_explicitly_wired"


def main():
    tests = [
        test_vm_resource_readiness_is_non_authoritative,
        test_vm_resource_readiness_reports_missing_credentials,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} VM resource readiness tests passed.")


if __name__ == "__main__":
    main()
