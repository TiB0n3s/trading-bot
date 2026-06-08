#!/usr/bin/env python3
"""Post-session symbol momentum timing intelligence report."""

from __future__ import annotations

import argparse
from datetime import datetime
from pathlib import Path

import pytz
from policy_artifacts import atomic_write_json

from services.symbol_momentum_timing_service import build_default_symbol_momentum_timing_service

ET = pytz.timezone("America/New_York")
BASE_DIR = Path(__file__).resolve().parent
MEMORY_FILE = BASE_DIR / "symbol_momentum_timing_memory.json"


def _fmt(value, width=7):
    if value is None:
        return f"{'-':>{width}}"
    if isinstance(value, float):
        return f"{value:>{width}.3f}"
    return f"{str(value):>{width}}"


def print_windows(title: str, rows: list[dict], limit: int) -> None:
    print()
    print(title)
    print(f"  {'Time':<19} {'Sym':<6} {'Fwd15':>7} {'Fwd30':>7} {'Score':>5} {'VWAP':>7} Setup")
    for row in rows[:limit]:
        print(
            f"  {str(row.get('timestamp') or '-'):<19} "
            f"{str(row.get('symbol') or '-'):<6} "
            f"{_fmt(row.get('ret_fwd_15m'))} "
            f"{_fmt(row.get('ret_fwd_30m'))} "
            f"{_fmt(row.get('state_score'), 5)} "
            f"{_fmt(row.get('distance_from_vwap'))} "
            f"{row.get('setup_label') or '-'}"
        )


def print_symbol_summary(memory: dict, limit: int) -> None:
    symbols = memory.get("symbol_memory") or {}
    rows = [(sym, payload) for sym, payload in symbols.items() if isinstance(payload, dict)]

    print()
    print("Symbol Timing Summary")
    print(
        f"  {'Sym':<6} {'Rows':>5} {'Sess%':>7} {'AvgF15':>7} "
        f"{'LongW':>6} {'ShortW':>6} Recommendation"
    )
    ranked = sorted(
        rows,
        key=lambda item: (
            item[1].get("long_state_windows", 0) + item[1].get("short_state_windows", 0),
            abs(float(item[1].get("avg_ret_fwd_15m") or 0)),
        ),
        reverse=True,
    )
    for sym, payload in ranked[:limit]:
        print(
            f"  {sym:<6} "
            f"{payload.get('rows', 0):>5} "
            f"{_fmt(payload.get('session_return_pct'))} "
            f"{_fmt(payload.get('avg_ret_fwd_15m'))} "
            f"{payload.get('long_state_windows', 0):>6} "
            f"{payload.get('short_state_windows', 0):>6} "
            f"{payload.get('recommendation') or '-'}"
        )


def print_setup_summary(memory: dict, limit: int) -> None:
    setups = memory.get("setup_memory") or {}
    rows = [(setup, payload) for setup, payload in setups.items() if isinstance(payload, dict)]

    print()
    print("Setup Timing Summary")
    print(f"  {'Setup':<38} {'Rows':>5} {'Fwd15':>7} {'Fwd30':>7} {'LongWin%':>8} {'ShortWin%':>9}")
    for setup, payload in sorted(rows, key=lambda item: item[1].get("rows", 0), reverse=True)[
        :limit
    ]:
        print(
            f"  {setup:<38} "
            f"{payload.get('rows', 0):>5} "
            f"{_fmt(payload.get('avg_ret_fwd_15m'))} "
            f"{_fmt(payload.get('avg_ret_fwd_30m'))} "
            f"{_fmt(payload.get('long_win_rate_15m_pct'), 8)} "
            f"{_fmt(payload.get('short_win_rate_15m_pct'), 9)}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=datetime.now(ET).date().isoformat())
    parser.add_argument("--symbol")
    parser.add_argument("--limit", type=int)
    parser.add_argument("--top-n", type=int, default=5)
    parser.add_argument("--samples", type=int, default=15)
    parser.add_argument("--write-memory", action="store_true")
    parser.add_argument("--output", default=str(MEMORY_FILE))
    args = parser.parse_args()

    service = build_default_symbol_momentum_timing_service()
    memory = service.analyze(
        target_date=args.date,
        symbol=args.symbol,
        limit=args.limit,
        top_n=args.top_n,
    )

    print("=" * 72)
    print(f"  Symbol Momentum Timing Report - {args.date}")
    print("=" * 72)
    print(f"Rows loaded     : {memory.get('row_count', 0)}")
    print(f"Complete labels : {memory.get('complete_row_count', 0)}")
    print(f"Symbols         : {memory.get('symbol_count', 0)}")

    print_symbol_summary(memory, limit=args.samples)
    print_setup_summary(memory, limit=args.samples)
    print_windows("Best Hindsight Long Windows", memory.get("top_long_windows") or [], args.samples)
    print_windows(
        "Best Hindsight Short/Sell Windows", memory.get("top_short_windows") or [], args.samples
    )

    if args.write_memory:
        output = Path(args.output)
        atomic_write_json(output, memory)
        print()
        print(f"Wrote {output}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
