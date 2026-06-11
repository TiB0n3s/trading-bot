#!/usr/bin/env python3
"""Contracts for intraday context refresh event collection."""

from __future__ import annotations

import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT / "src"))

os.environ.setdefault("ALPACA_API_KEY", "test-key")
os.environ.setdefault("ALPACA_SECRET_KEY", "test-secret")

import intraday_context_refresh  # noqa: E402


def test_intraday_event_collection_uses_hybrid_context_without_prediction_writes():
    captured: dict[str, object] = {}
    original_run = intraday_context_refresh.subprocess.run

    def fake_run(cmd, cwd=None, timeout=None):
        captured["cmd"] = list(cmd)
        captured["cwd"] = cwd
        captured["timeout"] = timeout
        return SimpleNamespace(returncode=0)

    intraday_context_refresh.subprocess.run = fake_run
    try:
        rc = intraday_context_refresh._collect_events("2026-06-11")
    finally:
        intraday_context_refresh.subprocess.run = original_run

    assert rc == 0
    cmd = captured["cmd"]
    assert "--date" in cmd
    assert cmd[cmd.index("--date") + 1] == "2026-06-11"
    assert "--max-per-symbol" in cmd
    assert cmd[cmd.index("--max-per-symbol") + 1] == "1"
    assert "--ai-interpret-events" in cmd
    assert "--ai-event-provider" in cmd
    assert cmd[cmd.index("--ai-event-provider") + 1] == "hybrid"
    assert "--apply-context" in cmd
    assert "--predict" not in cmd
    assert captured["cwd"] == intraday_context_refresh.SCRIPT_DIR
    assert captured["timeout"] == 180


def main():
    tests = [test_intraday_event_collection_uses_hybrid_context_without_prediction_writes]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} intraday context refresh tests passed.")


if __name__ == "__main__":
    main()
