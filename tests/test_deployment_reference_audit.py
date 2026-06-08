#!/usr/bin/env python3
"""Tests for deployment reference audits."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from ops.deployment_reference_audit import missing_references_in_text  # noqa: E402


def assert_equal(actual, expected, label):
    if actual != expected:
        raise AssertionError(f"{label}: expected {expected!r}, got {actual!r}")


def test_missing_references_suggest_scripts_path():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "scripts").mkdir()
        (root / "scripts" / "daily_summary.py").write_text("print('ok')\n")
        text = (
            "* * * * * cd /home/tradingbot/trading-bot && "
            "/home/tradingbot/trading-bot/venv/bin/python daily_summary.py\n"
        )

        missing = missing_references_in_text(text, source="crontab", repo_root=root)

    assert_equal(len(missing), 1, "missing count")
    assert_equal(missing[0].reference, "daily_summary.py", "reference")
    assert_equal(missing[0].suggested_path, "scripts/daily_summary.py", "suggestion")


def test_existing_references_pass():
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        (root / "scripts").mkdir()
        (root / "scripts" / "daily_summary.py").write_text("print('ok')\n")
        text = (
            "* * * * * cd /home/tradingbot/trading-bot && "
            "/home/tradingbot/trading-bot/venv/bin/python scripts/daily_summary.py\n"
        )

        missing = missing_references_in_text(text, source="crontab", repo_root=root)

    assert_equal(len(missing), 0, "missing count")


def main():
    tests = [
        test_missing_references_suggest_scripts_path,
        test_existing_references_pass,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} deployment reference audit tests passed.")


if __name__ == "__main__":
    main()
