#!/usr/bin/env python3
"""Tests for feature flag inventory diagnostics."""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.feature_flag_inventory_service import build_feature_flag_inventory  # noqa: E402


def test_feature_flag_inventory_discovers_authority_and_rollback_fields():
    with TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        (base_dir / "runtime_config.py").write_text(
            "\n".join(
                [
                    "import os",
                    "LIVE_TRADING_ENABLED = os.getenv('LIVE_TRADING_ENABLED', 'false')",
                    "ML_AUTHORITY_MODE = os.getenv('ML_AUTHORITY_MODE', 'observe_only_compare')",
                    "SOME_API_KEY = os.getenv('SOME_API_KEY', '')",
                ]
            ),
            encoding="utf-8",
        )
        payload = build_feature_flag_inventory(base_dir=base_dir)

    names = {row["name"]: row for row in payload["flags"]}
    assert payload["ready"] is True
    assert "LIVE_TRADING_ENABLED" in names
    assert "ML_AUTHORITY_MODE" in names
    assert "SOME_API_KEY" not in names
    assert names["LIVE_TRADING_ENABLED"]["authority_level"] == "high"
    assert (
        names["ML_AUTHORITY_MODE"]["rollback_action"]
        == "set to observe_only, compare, warn, or off"
    )


def main():
    tests = [
        test_feature_flag_inventory_discovers_authority_and_rollback_fields,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print(f"\nAll {len(tests)} feature flag inventory tests passed.")


if __name__ == "__main__":
    main()
