#!/usr/bin/env python3
"""
Run targeted trading-bot tests.

Usage:
  python3 run_tests.py
"""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent

TESTS = [
    "tests/test_trend.py",
    "tests/test_trade_matcher.py",
]


def main():
    print("=" * 64)
    print("  Trading Bot Targeted Tests")
    print("=" * 64)

    failures = 0

    for test in TESTS:
        print()
        print("──", test, "─" * max(0, 56 - len(test)))
        result = subprocess.run([sys.executable, test], cwd=ROOT)
        if result.returncode != 0:
            failures += 1

    print()
    print("=" * 64)
    if failures:
        print(f"[FAIL] {failures} test file(s) failed")
        return 1

    print(f"[OK] all {len(TESTS)} test file(s) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
