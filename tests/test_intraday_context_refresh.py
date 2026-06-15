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


def test_reuse_existing_market_data_builds_from_context_snapshots():
    original_symbols = intraday_context_refresh.APPROVED_SYMBOLS_LIST
    intraday_context_refresh.APPROVED_SYMBOLS_LIST = ["AAPL", "MSFT"]
    try:
        market_data = intraday_context_refresh._market_data_from_existing_context(
            {
                "symbols": {
                    "AAPL": {
                        "data_snapshot": {
                            "daily_pct": 1.2,
                            "intraday_pct": 0.4,
                            "momentum_30m_pct": 0.1,
                            "last_price": 199.5,
                            "bar_count_1m": 120,
                        },
                        "support_levels": [197.0],
                        "resistance_levels": [202.0],
                    },
                    "MSFT": {},
                }
            }
        )
    finally:
        intraday_context_refresh.APPROVED_SYMBOLS_LIST = original_symbols

    assert list(market_data) == ["AAPL"]
    assert market_data["AAPL"]["last_price"] == 199.5
    assert market_data["AAPL"]["support_levels"] == [197.0]
    assert market_data["AAPL"]["resistance_levels"] == [202.0]
    assert market_data["AAPL"]["source"] == "existing_market_context"


def main():
    tests = [
        test_intraday_event_collection_uses_hybrid_context_without_prediction_writes,
        test_reuse_existing_market_data_builds_from_context_snapshots,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} intraday context refresh tests passed.")


if __name__ == "__main__":
    main()
