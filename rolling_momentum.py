#!/usr/bin/env python3
"""
Rolling multi-day momentum context entrypoint.

Builds rolling_momentum.json for all approved symbols. Market-data access and
context computation live in services/rolling_momentum_service.py.
"""

from __future__ import annotations

import json
import sys
from datetime import datetime
from pathlib import Path

from market_time import now_et
from services.rolling_momentum_service import (
    RollingMomentumService,
    as_et,
    classify_context,
    pct_change,
    safe_round,
    session_bucket,
    summarize_day,
)
from symbols_config import APPROVED_SYMBOLS_LIST

BASE_DIR = Path(__file__).resolve().parent
OUTPUT_FILE = BASE_DIR / "rolling_momentum.json"

_service = RollingMomentumService()


def fetch_minute_bars(symbol):
    return _service.fetch_minute_bars(symbol)


def build_symbol_context(symbol):
    return _service.build_symbol_context(symbol)


def main():
    started = datetime.now()
    results = {}

    for sym in APPROVED_SYMBOLS_LIST:
        print(f"Processing {sym}...")
        results[sym] = build_symbol_context(sym)

    output = {
        "generated_at": datetime.now().isoformat(),
        "market_time_et": now_et().isoformat(),
        "source": "rolling_momentum.py",
        "mode": "live_context_provider",
        "symbols_count": len(APPROVED_SYMBOLS_LIST),
        "symbols": results,
    }

    OUTPUT_FILE.write_text(json.dumps(output, indent=2))

    elapsed = (datetime.now() - started).total_seconds()

    print()
    print("=" * 96)
    print("  Rolling Momentum Context - Live Context Provider")
    print("=" * 96)
    print(f"  Output  : {OUTPUT_FILE}")
    print(f"  Symbols : {len(results)}")
    print(f"  Elapsed : {elapsed:.1f}s")
    print(f"rows_written: {len(results)}")
    print()
    print(f"{'Symbol':<7} {'Context':<32} {'Score':>5} {'5d%':>8} {'Pre%':>8} {'Gap%':>8} {'Sess%':>8} {'Special'}")
    print(f"{'-'*7} {'-'*32} {'-'*5} {'-'*8} {'-'*8} {'-'*8} {'-'*8} {'-'*30}")

    for sym in APPROVED_SYMBOLS_LIST:
        row = results.get(sym, {})
        print(
            f"{sym:<7} "
            f"{str(row.get('trend_context', 'unknown')):<32} "
            f"{str(row.get('continuation_score', 0)):>5} "
            f"{str(row.get('five_day_return_pct')):>8} "
            f"{str(row.get('premarket_return_pct')):>8} "
            f"{str(row.get('overnight_gap_pct')):>8} "
            f"{str(row.get('current_session_return_pct')):>8} "
            f"{','.join(row.get('special_labels', []) or [])[:30]}"
        )


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
