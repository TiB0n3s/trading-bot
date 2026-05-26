#!/usr/bin/env python3
"""
Run targeted trading-bot tests.

Usage:
  python3 run_tests.py
"""

import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
ENV_FILE = Path("/etc/trading-bot.env")
VENV_PYTHON = ROOT / "venv" / "bin" / "python"


def reexec_under_venv_if_available():
    if not VENV_PYTHON.exists():
        return

    venv_dir = VENV_PYTHON.parent.parent.resolve()
    current_prefix = Path(sys.prefix).resolve()
    if current_prefix == venv_dir:
        return

    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve())] + sys.argv[1:])


def load_env_file(path=ENV_FILE):
    if not path.exists():
        return False

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")

        if key and key not in os.environ:
            os.environ[key] = value

    return True


TESTS = [
    "tests/test_market_time.py",
    "tests/test_rejection_categories.py",
    "tests/test_symbols_config.py",
    "tests/test_auto_buy_manager.py",
    "tests/test_market_context_schema.py",
    "tests/test_setup_policy.py",
    "tests/test_rejected_signal_outcomes.py",
    "tests/test_broker.py",
    "tests/test_db_migrations.py",
    "tests/test_fill_stream.py",
    "tests/test_trend.py",
    "tests/test_fast_lane.py",
    "tests/test_fast_lane_sell.py",
    "tests/test_position_manager.py",
    "tests/test_trade_matcher.py",
    "tests/test_live_bias_override.py",
    "tests/test_macro_risk.py",
    "tests/test_pnl.py",
]


def main():
    reexec_under_venv_if_available()
    env_loaded = load_env_file()

    print("=" * 64)
    print("  Trading Bot Targeted Tests")
    print("=" * 64)
    print(f"env_file_loaded={env_loaded}")

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
