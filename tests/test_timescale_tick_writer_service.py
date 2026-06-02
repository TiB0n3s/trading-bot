#!/usr/bin/env python3
"""Tests for optional Timescale tick writer behavior without a DB."""

from __future__ import annotations

import asyncio
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.timescale_tick_writer_service import ensure_timescale_schema, write_ticks


def test_timescale_writer_is_disabled_without_uri():
    old = os.environ.pop("TIMESCALE_DB_URI", None)
    try:
        schema = asyncio.run(ensure_timescale_schema()).to_dict()
        write = asyncio.run(write_ticks([{"ticker": "AAPL", "price": 1, "volume": 1}])).to_dict()
    finally:
        if old is not None:
            os.environ["TIMESCALE_DB_URI"] = old

    assert schema["enabled"] is False
    assert "not configured" in schema["reason"]
    assert write["enabled"] is False


def main():
    test_timescale_writer_is_disabled_without_uri()
    print("[OK] test_timescale_writer_is_disabled_without_uri")
    print("\nAll 1 Timescale tick writer tests passed.")


if __name__ == "__main__":
    main()
