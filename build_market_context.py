#!/usr/bin/env python3
"""
Build market_context.json from raw research JSON.

This is the CLI bridge between automated research and the normalized richer
market_context.json schema.

Safe by default:
- requires --input
- writes to --output
- does not place orders
- does not contact broker
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from market_intelligence.market_brief_builder import build_from_file, summary_for_brief


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, help="Raw research JSON input path")
    parser.add_argument(
        "--output",
        default="market_context.json",
        help="Output path, default market_context.json",
    )
    parser.add_argument("--date", help="Override market_date YYYY-MM-DD")
    parser.add_argument(
        "--print-summary",
        action="store_true",
        help="Print schema quality summary after building",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    if not input_path.exists():
        raise SystemExit(f"ERROR: input file not found: {input_path}")

    brief = build_from_file(
        input_path=input_path,
        output_path=output_path,
        market_date=args.date,
    )

    print(f"Wrote {output_path}")
    print(f"market_date={brief.get('market_date')}")
    print(f"source={brief.get('source')}")
    print(f"format={brief.get('format')}")
    print(f"symbols={len(brief.get('symbols') or {})}")

    if args.print_summary:
        print(json.dumps(summary_for_brief(brief), indent=2, sort_keys=True))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
