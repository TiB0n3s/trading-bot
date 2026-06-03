#!/usr/bin/env python3
"""Tests for automated retraining operational guardrails."""

from __future__ import annotations

from argparse import Namespace
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import retrain


def test_retrain_lock_reports_busy_when_already_held():
    with tempfile.TemporaryDirectory() as tmp:
        lock_file = str(Path(tmp) / "retrain.lock")
        with retrain._nonblocking_lock(lock_file) as first_acquired:
            assert first_acquired is True
            with retrain._nonblocking_lock(lock_file) as second_acquired:
                assert second_acquired is False


def test_main_returns_timeout_status_without_live_authority():
    original_parse = retrain._parse_args
    original_execute = retrain._execute_retraining

    def fake_parse():
        return Namespace(
            lock_file="",
            max_runtime_seconds=0,
            json=True,
        )

    def fake_execute(args):  # noqa: ARG001
        raise retrain.RetrainingTimeout("test timeout")

    try:
        retrain._parse_args = fake_parse
        retrain._execute_retraining = fake_execute
        assert retrain.main() == 124
    finally:
        retrain._parse_args = original_parse
        retrain._execute_retraining = original_execute


def main():
    tests = [
        test_retrain_lock_reports_busy_when_already_held,
        test_main_returns_timeout_status_without_live_authority,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} pipeline retrain tests passed.")


if __name__ == "__main__":
    main()
