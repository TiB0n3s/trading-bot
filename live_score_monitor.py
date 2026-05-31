#!/usr/bin/env python3
"""
Live symbol score monitor.

Read-only. Does not affect trading behavior.

Shows how symbol scores evolve intraday using:
- auto_buy_candidates
- session_momentum
- feature_snapshots
- recent trades/rejections
"""

from __future__ import annotations

import argparse
import os
import time
from datetime import datetime

from repositories.reporting_repo import ReportingRepository


repo = ReportingRepository()


def val(row, key, default=""):
    if not row:
        return default
    v = row.get(key)
    if v is None:
        return default
    return v


def fnum(v, digits=2, default=""):
    try:
        return f"{float(v):.{digits}f}"
    except Exception:
        return default


def trim(text, n=48):
    text = str(text or "")
    return text if len(text) <= n else text[: n - 1] + "…"


def clear():
    os.system("clear")


def render(symbols: list[str] | None, history_symbol: str | None, limit: int):
        auto_cols = repo.table_columns("auto_buy_candidates")
        feature_cols = repo.table_columns("feature_snapshots")
        session_cols = repo.table_columns("session_momentum")

        auto = repo.latest_by_symbol("auto_buy_candidates", "timestamp", symbols) if auto_cols else {}
        session = repo.latest_by_symbol("session_momentum", "updated_at", symbols) if session_cols else {}
        feature = repo.latest_by_symbol("feature_snapshots", "timestamp", symbols) if feature_cols else {}

        all_symbols = sorted(set(auto) | set(session) | set(feature))
        if symbols:
            all_symbols = [s for s in symbols if s in set(all_symbols)]

        def sort_key(sym):
            a = auto.get(sym) or {}
            s = session.get(sym) or {}
            return (
                float(val(a, "score", -999) or -999),
                float(val(s, "trend_score", -999) or -999),
            )

        all_symbols = sorted(all_symbols, key=sort_key, reverse=True)[:limit]

        print("=" * 180)
        print(f"Live Score Monitor — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        print("=" * 180)
        print(
            f"{'Sym':<6} "
            f"{'Auto':>6} {'Decision':<22} "
            f"{'Sess':>5} {'Label':<18} {'Ret%':>7} {'M15%':>7} {'M30%':>7} "
            f"{'Setup':>6} {'Setup label':<34} "
            f"{'RS5':>7} {'Accel':>7} "
            f"{'Block / reason':<42}"
        )
        print("-" * 180)

        for sym in all_symbols:
            a = auto.get(sym) or {}
            s = session.get(sym) or {}
            f = feature.get(sym) or {}

            accel = ""
            for k in ("momentum_acceleration_pct", "acceleration_pct", "momentum_acceleration"):
                if k in f:
                    accel = fnum(f.get(k), 3)
                    break

            block = val(a, "hard_block_reason") or val(a, "live_block_reason") or val(a, "reason")

            print(
                f"{sym:<6} "
                f"{fnum(val(a, 'score'), 2):>6} {trim(val(a, 'decision'), 22):<22} "
                f"{fnum(val(s, 'trend_score'), 0):>5} {trim(val(s, 'trend_label'), 18):<18} "
                f"{fnum(val(s, 'session_return_pct'), 3):>7} "
                f"{fnum(val(s, 'momentum_15m_pct'), 3):>7} "
                f"{fnum(val(s, 'momentum_30m_pct'), 3):>7} "
                f"{fnum(val(f, 'setup_score'), 0):>6} {trim(val(f, 'setup_label'), 34):<34} "
                f"{fnum(val(f, 'relative_strength_5m'), 3):>7} "
                f"{accel:>7} "
                f"{trim(block, 42):<42}"
            )

        print()
        print("Recent BUY rejections")
        print("-" * 180)
        for r in repo.recent_buy_rejections(10, symbols):
            print(f"{r['timestamp']} {r['symbol']:<6} {trim(r['rejection_reason'], 150)}")

        if history_symbol:
            print()
            print(f"Auto-buy score history — {history_symbol}")
            print("-" * 180)
            rows = list(reversed(repo.auto_buy_score_history(history_symbol.upper(), 20)))
            for r in rows:
                print(
                    f"{r['timestamp']}  "
                    f"score={fnum(r['score'], 2):>6}  "
                    f"decision={trim(r['decision'], 24):<24}  "
                    f"block={trim(r['hard_block_reason'], 80)}"
                )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--symbols", default="", help="Comma-separated symbols to monitor")
    ap.add_argument("--history-symbol", default="", help="Symbol to show score history for")
    ap.add_argument("--refresh", type=int, default=20)
    ap.add_argument("--limit", type=int, default=35)
    ap.add_argument("--once", action="store_true")
    args = ap.parse_args()

    symbols = [s.strip().upper() for s in args.symbols.split(",") if s.strip()] or None
    history_symbol = args.history_symbol.strip().upper() or None

    while True:
        clear()
        render(symbols, history_symbol, args.limit)

        if args.once:
            break

        time.sleep(args.refresh)


if __name__ == "__main__":
    main()
