#!/usr/bin/env python3
"""
Concise intelligence status report.

Reads generated memory files and recent bot_events.
"""

import json
from datetime import datetime
from pathlib import Path

from bot_events import fetch_events
from intelligence_freshness import get_intelligence_freshness

BASE_DIR = Path(__file__).resolve().parent

FILES = {
    "strategy_memory": BASE_DIR / "strategy_memory.json",
    "missed_opportunity": BASE_DIR / "missed_opportunity_memory.json",
    "excursion": BASE_DIR / "excursion_memory.json",
    "policy_backtest": BASE_DIR / "policy_backtest_summary.json",
    "portfolio_replacement": BASE_DIR / "portfolio_replacement_memory.json",
}


def load(path):
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text())
    except Exception:
        return None


def age_label(path):
    if not path.exists():
        return "missing"
    try:
        mtime = datetime.fromtimestamp(path.stat().st_mtime)
        delta = datetime.now() - mtime
        mins = int(delta.total_seconds() // 60)
        if mins < 60:
            return f"{mins}m old"
        return f"{mins // 60}h {mins % 60}m old"
    except Exception:
        return "unknown age"


def main():
    data = {k: load(v) for k, v in FILES.items()}

    print("=" * 72)
    print("  Intelligence Status")
    print("=" * 72)

    print()
    print("Files:")
    for key, path in FILES.items():
        obj = data.get(key)
        print(
            f"  {key:<24} "
            f"{'loaded' if obj else 'missing/error':<14} "
            f"{age_label(path):<12} "
            f"generated_at={(obj or {}).get('generated_at') or '-'}"
        )

    strategy = data.get("strategy_memory") or {}
    policy = data.get("policy_backtest") or {}
    missed = data.get("missed_opportunity") or {}
    replacement = data.get("portfolio_replacement") or {}

    print()
    print("Freshness:")
    freshness = get_intelligence_freshness()
    for key, info in freshness.items():
        print(
            f"  {key:<24} {info.get('status'):<8} "
            f"age={info.get('age_minutes')}m "
            f"max={info.get('max_age_minutes')}m "
            f"{info.get('reason')}"
        )

    print()
    print("Brain:")
    print(f"  strategy trade_count        : {strategy.get('trade_count')}")
    print(f"  manual overrides            : {strategy.get('manual_overrides_applied')}")
    print(
        f"  policy recommendation       : {policy.get('recommendation')} - {policy.get('reason')}"
    )
    print(
        f"  replacement recommendation  : {replacement.get('recommendation')} - {replacement.get('reason')}"
    )

    weakest = replacement.get("weakest_holding") or {}
    strongest = replacement.get("strongest_candidate") or {}
    if weakest:
        print(
            f"  weakest holding             : {weakest.get('symbol')} "
            f"{float(weakest.get('unrealized_plpc') or 0):+.2f}%"
        )
    if strongest:
        print(
            f"  strongest candidate         : {strongest.get('symbol')} "
            f"score={strongest.get('score')} "
            f"decision={strongest.get('decision')}"
        )

    missed_cats = missed.get("category_memory") or {}
    macro = missed_cats.get("macro_position_limit") or {}
    if macro:
        print(
            f"  macro_position_limit memory : {macro.get('recommendation')} "
            f"avg30m={macro.get('avg_30m_return_pct')} "
            f"missed_good={macro.get('missed_good_rate_pct')}%"
        )

    print()
    print("Recent bot events:")
    rows = fetch_events(limit=12)
    if not rows:
        print("  none")
    else:
        for r in rows:
            print(
                f"  {r['timestamp']} "
                f"{r['event_type']:<26} "
                f"{str(r['symbol'] or '-'):<6} "
                f"{str(r['decision'] or '-'):<16} "
                f"{str(r['reason'] or '')[:70]}"
            )


if __name__ == "__main__":
    main()
