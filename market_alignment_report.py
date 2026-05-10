#!/usr/bin/env python3
"""
Market alignment report — observe-only.

Shows whether each approved symbol's current market bias is aligned with its
benchmark/index context.

Usage:
  python3 market_alignment_report.py
"""

import json
from pathlib import Path
from datetime import datetime

import pytz

from config import APPROVED_SYMBOLS, SYMBOL_MARKET_ALIGNMENT
from app import _compute_trend
from db import DB_PATH, get_connection

BASE_DIR = Path(__file__).resolve().parent
MARKET_CONTEXT = BASE_DIR / "market_context.json"


def short(v, width):
    if v is None:
        return "-"
    s = str(v)
    return s if len(s) <= width else s[: width - 1] + "…"


def load_market_context():
    if not MARKET_CONTEXT.exists():
        return {}
    return json.loads(MARKET_CONTEXT.read_text())


def recent_actions(symbol, limit=10):
    with get_connection(DB_PATH) as con:
        rows = con.execute(
            """
            SELECT action
            FROM trades
            WHERE symbol = ?
              AND action IS NOT NULL
              AND (
                    approved = 1
                 OR rejection_reason LIKE 'confidence_gate:%'
                 OR rejection_reason LIKE 'trend_gate:%'
                 OR rejection_reason LIKE 'trend_confirmation:%'
              )
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (symbol, limit),
        ).fetchall()

    return [r["action"] for r in rows]


def alignment_for(symbol, ctx):
    symbols = ctx.get("symbols") or {}
    mapping = SYMBOL_MARKET_ALIGNMENT.get(symbol, {"cluster": "unknown", "benchmark": "SPY"})

    cluster = mapping.get("cluster", "unknown")
    benchmark = mapping.get("benchmark", "SPY")

    symbol_ctx = symbols.get(symbol) or {}
    benchmark_ctx = symbols.get(benchmark) or {}

    benchmark_trend = _compute_trend(recent_actions(benchmark))

    symbol_bias = symbol_ctx.get("bias")
    benchmark_bias = benchmark_ctx.get("bias")
    benchmark_direction = benchmark_trend.get("direction")
    benchmark_strength = benchmark_trend.get("strength")

    aligned = True
    reason = []

    if symbol_bias == "avoid":
        aligned = False
        reason.append("symbol avoid")

    if benchmark_bias == "avoid":
        aligned = False
        reason.append("benchmark avoid")

    if benchmark_direction == "bearish":
        aligned = False
        reason.append("benchmark bearish")

    if benchmark_direction == "neutral" and benchmark_strength == "weak":
        reason.append("benchmark neutral/weak")

    if aligned and not reason:
        reason.append("aligned")

    return {
        "symbol": symbol,
        "cluster": cluster,
        "benchmark": benchmark,
        "symbol_bias": symbol_bias,
        "risk_level": symbol_ctx.get("risk_level"),
        "entry_quality": symbol_ctx.get("entry_quality"),
        "benchmark_bias": benchmark_bias,
        "benchmark_trend": f"{benchmark_direction}/{benchmark_strength}",
        "benchmark_count": benchmark_trend.get("consecutive_count"),
        "aligned": aligned,
        "reason": "; ".join(reason),
    }


def context_freshness(ctx):
    market_date = ctx.get("market_date")
    today_et = datetime.now(pytz.timezone("America/New_York")).date().isoformat()

    if market_date == today_et:
        return "fresh", f"market_date matches today ({today_et})"

    return "stale", f"market_date={market_date}, today={today_et}"


def gate_readiness(rows, freshness):
    if freshness != "fresh":
        return "observe_only_not_ready"

    weak_benchmarks = [
        r for r in rows
        if r.get("benchmark_trend") in ("neutral/weak", "-/weak", "None/None")
    ]

    if len(weak_benchmarks) > len(rows) // 2:
        return "observe_only_weak_benchmark_data"

    return "observe_only_ready_for_review"


def main():
    ctx = load_market_context()
    rows = [alignment_for(sym, ctx) for sym in sorted(APPROVED_SYMBOLS)]

    print("=" * 132)
    print("  Market Alignment Report")
    print("=" * 132)
    freshness, freshness_reason = context_freshness(ctx)
    readiness = gate_readiness(rows, freshness)

    print(f"  market_date       : {ctx.get('market_date')}")
    print(f"  macro_sentiment   : {ctx.get('macro_sentiment')}")
    print(f"  source            : {ctx.get('source')}")
    print(f"  context_freshness : {freshness} ({freshness_reason})")
    print(f"  trend_source      : bot signal history, not live index market data")
    print(f"  gate_readiness    : {readiness}")
    print()

    headers = [
        "Sym", "Cluster", "Bench", "SymBias", "Risk", "Entry",
        "BenchBias", "BenchTrend", "Cnt", "Aligned", "Reason"
    ]
    widths = [6, 20, 7, 9, 10, 18, 10, 18, 5, 8, 28]
    fmt = " ".join(f"{{:<{w}}}" for w in widths)

    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))

    aligned_count = 0
    blocked_count = 0

    for r in rows:
        if r["aligned"]:
            aligned_count += 1
        else:
            blocked_count += 1

        print(fmt.format(
            r["symbol"],
            short(r["cluster"], 20),
            r["benchmark"],
            short(r["symbol_bias"], 9),
            short(r["risk_level"], 10),
            short(r["entry_quality"], 18),
            short(r["benchmark_bias"], 10),
            short(r["benchmark_trend"], 18),
            str(r["benchmark_count"]),
            "yes" if r["aligned"] else "no",
            short(r["reason"], 28),
        ))

    print()
    print(f"Aligned for BUY context : {aligned_count}")
    print(f"Not aligned / avoid     : {blocked_count}")
    print()
    print("Observe-only: this report does not block trades.")
    print("Do not promote to a hard gate unless context_freshness is fresh and gate_readiness is reviewed.")


if __name__ == "__main__":
    main()
