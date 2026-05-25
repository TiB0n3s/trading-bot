#!/usr/bin/env python3
"""Run staged/ahead-of-live integration tests.

These tests cover observe-only or future integration paths. They must not be
required for live behavior to change, but they should stay green before staged
code is promoted.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / "venv" / "bin" / "python"

STAGED_TESTS = [
    "tests/staged/test_ml_platform_staged.py",
]


def reexec_under_venv_if_available() -> None:
    if not VENV_PYTHON.exists():
        return

    venv_dir = VENV_PYTHON.parent.parent.resolve()
    current_prefix = Path(sys.prefix).resolve()
    if current_prefix == venv_dir:
        return

    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve())] + sys.argv[1:])


def main() -> int:
    reexec_under_venv_if_available()

    print("=" * 64)
    print("  Trading Bot Staged Integration Tests")
    print("=" * 64)
    print("runtime_effect=none")

    failures = 0
    for test in STAGED_TESTS:
        print()
        print("--", test, "-" * max(0, 56 - len(test)))
        result = subprocess.run([sys.executable, test], cwd=ROOT)
        if result.returncode != 0:
            failures += 1

    print()
    print("=" * 64)
    if failures:
        print(f"[FAIL] {failures} staged test file(s) failed")
        return 1

    print(f"[OK] all {len(STAGED_TESTS)} staged test file(s) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
