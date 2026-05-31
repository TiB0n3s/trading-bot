#!/usr/bin/env python3
"""Lightweight tests for ops_check.py command routing."""

from __future__ import annotations

import io
import sqlite3
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import ops_check


def _run_cli(tmp_path: Path, *args: str) -> tuple[int, str]:
    old_argv = sys.argv[:]
    old_base = ops_check.BASE_DIR
    old_env_file = ops_check.ENV_FILE
    try:
        sys.argv = ["ops_check.py", *args]
        ops_check.BASE_DIR = tmp_path
        ops_check.ENV_FILE = tmp_path / "missing.env"
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = ops_check.main()
        return code, buf.getvalue()
    finally:
        sys.argv = old_argv
        ops_check.BASE_DIR = old_base
        ops_check.ENV_FILE = old_env_file


def test_feature_attribution_cli_missing_db_exits_cleanly(tmp_path):
    code, out = _run_cli(tmp_path, "feature-attribution", "2026-05-30")

    assert code == 1
    assert "Feature Attribution Report" in out
    assert "[WARN] trades.db not found" in out


def test_post_trade_learning_cli_missing_db_exits_cleanly(tmp_path):
    code, out = _run_cli(tmp_path, "post-trade-learning", "2026-05-30")

    assert code == 1
    assert "Post-Trade Learning Report" in out
    assert "[WARN] trades.db not found" in out


def test_feature_attribution_cli_empty_lifecycle_rows_warns(tmp_path):
    with sqlite3.connect(tmp_path / "trades.db") as con:
        con.execute(
            """
            CREATE TABLE decision_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER,
                decision_time TEXT,
                symbol TEXT,
                action TEXT,
                approved INTEGER,
                final_decision TEXT,
                rejection_reason TEXT,
                canonical_intelligence_json TEXT
            )
            """
        )

    code, out = _run_cli(tmp_path, "feature-attribution", "2026-05-30")

    assert code == 1
    assert "rows_with_outcome       : 0" in out
    assert "[WARN] no lifecycle rows with realized/counterfactual outcomes" in out


def test_post_trade_learning_cli_empty_lifecycle_rows_warns(tmp_path):
    with sqlite3.connect(tmp_path / "trades.db") as con:
        con.execute(
            """
            CREATE TABLE decision_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                trade_id INTEGER,
                decision_time TEXT,
                symbol TEXT,
                action TEXT,
                approved INTEGER,
                final_decision TEXT,
                rejection_reason TEXT,
                canonical_intelligence_json TEXT
            )
            """
        )

    code, out = _run_cli(tmp_path, "post-trade-learning", "2026-05-30")

    assert code == 1
    assert "rows" in out and ": 0" in out
    assert "[WARN] no lifecycle rows found" in out


def main():
    tests = [
        test_feature_attribution_cli_missing_db_exits_cleanly,
        test_post_trade_learning_cli_missing_db_exits_cleanly,
        test_feature_attribution_cli_empty_lifecycle_rows_warns,
        test_post_trade_learning_cli_empty_lifecycle_rows_warns,
    ]
    for test in tests:
        with tempfile.TemporaryDirectory() as tmp:
            test(Path(tmp))
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} ops check CLI tests passed.")


if __name__ == "__main__":
    main()
