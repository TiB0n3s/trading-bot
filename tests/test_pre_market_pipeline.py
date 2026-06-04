#!/usr/bin/env python3
"""Tests for pre-market pipeline dependency wiring."""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from pipeline import pre_market


def test_pre_market_dry_run_persists_trend_context_before_events():
    old_argv = sys.argv[:]
    try:
        sys.argv = [
            "pipeline/pre_market.py",
            "--date",
            "2026-06-04",
            "--dry-run",
        ]
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = pre_market.main()
    finally:
        sys.argv = old_argv

    out = buf.getvalue()
    assert code == 0
    assert "Pre-market pipeline" in out
    assert "research_data" in out
    assert "historical_trend_context" in out
    assert "build_historical_trend_context" in out
    assert "collect_events" in out
    assert out.index("research_data") < out.index("historical_trend_context")
    assert out.index("historical_trend_context") < out.index("collect_events")


if __name__ == "__main__":
    test_pre_market_dry_run_persists_trend_context_before_events()
    print("pre-market pipeline tests passed")
