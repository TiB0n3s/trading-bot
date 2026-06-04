#!/usr/bin/env python3
"""Tests for conservative local-artifact cleanup defaults."""

from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SCRIPT = ROOT / "ops" / "clean_local_artifacts.sh"


def _run(*args: str) -> str:
    return subprocess.check_output(
        [str(SCRIPT), *args],
        cwd=ROOT,
        text=True,
        stderr=subprocess.STDOUT,
    )


def test_default_dry_run_excludes_operational_logs_and_db_backups():
    out = _run("--dry-run")

    assert "Dry run." in out or "No selected local artifacts found." in out
    assert "./live_features.log" not in out
    assert "./post_session_review.log" not in out
    assert "./trades.db.bak_auto_buy_attribution_20260602_121934" not in out


def test_explicit_flags_include_logs_and_db_backups():
    out = _run("--dry-run", "--include-logs", "--include-db-backups")

    assert "./live_features.log" in out
    assert "./trades.db.bak_auto_buy_attribution_20260602_121934" in out


if __name__ == "__main__":
    test_default_dry_run_excludes_operational_logs_and_db_backups()
    test_explicit_flags_include_logs_and_db_backups()
    print("clean local artifacts script tests passed")
