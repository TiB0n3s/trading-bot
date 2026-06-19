#!/usr/bin/env python3
"""
Market Context Report.

Read-only report for market_context.json freshness and symbol coverage.

Usage:
  python3 market_context_report.py
"""

import json
from collections import Counter
from datetime import datetime
from pathlib import Path
from market_intelligence.market_brief_schema import schema_quality_summary
import pytz

from config import APPROVED_SYMBOLS

BASE_DIR = Path(__file__).resolve().parent
MARKET_CONTEXT = BASE_DIR / "market_context.json"


def main() -> int:
    print("=" * 72)
    print("  Market Context Report")
    print("=" * 72)

    if not MARKET_CONTEXT.exists():
        print("[FAIL] market_context.json not found")
        return 1

    try:
        ctx = json.loads(MARKET_CONTEXT.read_text())
    except Exception as e:
        print(f"[FAIL] could not parse market_context.json: {e}")
        return 1

    today_et = datetime.now(pytz.timezone("America/New_York")).date().isoformat()
    symbols = ctx.get("symbols") or {}

    print(f"market_date     : {ctx.get('market_date')}")
    print(f"today_et        : {today_et}")
    print(f"macro_regime    : {ctx.get('macro_regime')}")
    print(f"macro_sentiment : {ctx.get('macro_sentiment')}")
    print(f"source          : {ctx.get('source')}")
    print(f"format          : {ctx.get('format')}")

    quality = schema_quality_summary(ctx)

    print()
    print("── Rich Schema Coverage ───────────────────────────────")
    print(f"index_state entries : {quality.get('index_state_count', 0)}")
    print(f"sector_state entries: {quality.get('sector_state_count', 0)}")
    print(f"macro_events        : {quality.get('macro_events_count', 0)}")

    rich_coverage = quality.get("rich_field_coverage") or {}
    symbol_count = quality.get("symbol_count") or len(symbols) or 1

    for field, count in sorted(rich_coverage.items()):
        pct = count / symbol_count * 100 if symbol_count else 0
        status = "[OK]" if pct >= 90 else "[WARN]" if pct >= 50 else "[LOW]"
        print(f"{status} {field:<28} {count:>3}/{symbol_count:<3} {pct:>6.1f}%")


    list_fields = [
        "key_catalysts",
        "key_risks",
        "support_levels",
        "resistance_levels",
    ]

    print()
    print("── Rich List Coverage ─────────────────────────────────")
    for field in list_fields:
        count = sum(
            1 for entry in symbols.values()
            if isinstance(entry, dict)
            and isinstance(entry.get(field), list)
            and len(entry.get(field)) > 0
        )
        pct = count / symbol_count * 100 if symbol_count else 0
        status = "[OK]" if pct >= 90 else "[WARN]" if pct >= 50 else "[LOW]"
        print(f"{status} {field:<28} {count:>3}/{symbol_count:<3} {pct:>6.1f}%")
        
    if ctx.get("market_date") == today_et:
        print("[OK]   market_context date matches today")
    else:
        print("[WARN] market_context date does not match today")

    missing = sorted(APPROVED_SYMBOLS - set(symbols))
    extra = sorted(set(symbols) - APPROVED_SYMBOLS)

    print()
    print("── Symbol Coverage ────────────────────────────────────")
    print(f"approved symbols : {len(APPROVED_SYMBOLS)}")
    print(f"context symbols  : {len(symbols)}")

    if missing:
        print(f"[FAIL] missing symbols: {missing}")
    else:
        print("[OK]   no approved symbols missing")

    if extra:
        print(f"[WARN] extra symbols: {extra}")

    bias_counts = Counter()
    risk_counts = Counter()
    entry_counts = Counter()

    for entry in symbols.values():
        if not isinstance(entry, dict):
            continue
        bias_counts[entry.get("bias") or "missing"] += 1
        risk_counts[entry.get("risk_level") or "missing"] += 1
        entry_counts[entry.get("entry_quality") or "missing"] += 1

    print()
    print("── Bias Counts ────────────────────────────────────────")
    for k, v in sorted(bias_counts.items()):
        print(f"{k:<20} {v:>4}")

    print()
    print("── Risk Counts ────────────────────────────────────────")
    for k, v in sorted(risk_counts.items()):
        print(f"{k:<20} {v:>4}")

    print()
    print("── Entry Quality Counts ───────────────────────────────")
    for k, v in sorted(entry_counts.items()):
        print(f"{k:<20} {v:>4}")

    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
