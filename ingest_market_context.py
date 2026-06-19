#!/usr/bin/env python3
"""
Ingest a market_context JSON file into daily_symbol_context.

Usage:
  python3 ingest_market_context.py market_context.json
  python3 ingest_market_context.py /tmp/market_context_2026-05-26.data.json
"""

import argparse
import json
from collections import Counter
from pathlib import Path

from db import DB_PATH, get_connection
from market_intelligence.intelligence_store import (
    init_intelligence_tables,
    ingest_market_context,
)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("input", help="Path to market_context-style JSON")
    args = parser.parse_args()

    path = Path(args.input)
    if not path.exists():
        raise SystemExit(f"ERROR: input file not found: {path}")

    init_intelligence_tables()
    summary = ingest_market_context(path)

    with get_connection(DB_PATH) as con:
        rows = con.execute(
            """
            SELECT symbol, bias, confidence, risk_level, entry_quality
            FROM daily_symbol_context
            WHERE market_date = ?
            ORDER BY symbol
            """,
            (summary["market_date"],),
        ).fetchall()

    bias_counts = Counter(r["bias"] for r in rows)

    print()
    print("=== Market context ingested ===")
    print(f"  Input       : {summary['path']}")
    print(f"  Market date : {summary['market_date']}")
    print(f"  Source      : {summary['source']}")
    print(f"  Symbols     : {summary['symbols']}")
    print(f"  Bias counts : {dict(bias_counts)}")
    print()
    print(f"  {'Symbol':<7} {'Bias':<8} {'Conf':<7} {'Risk':<10} {'Entry':<22}")
    print(f"  {'-'*7} {'-'*8} {'-'*7} {'-'*10} {'-'*22}")
    for r in rows:
        print(
            f"  {r['symbol']:<7} "
            f"{str(r['bias'] or '-'):<8} "
            f"{str(r['confidence'] or '-'):<7} "
            f"{str(r['risk_level'] or '-'):<10} "
            f"{str(r['entry_quality'] or '-'):<22}"
        )


if __name__ == "__main__":
    main()
