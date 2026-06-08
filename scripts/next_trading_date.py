#!/usr/bin/env python3
"""
Print the next regular US stock-market trading date.

Uses shared holiday-aware market calendar helpers from market_time.py.

Usage:
  python3 next_trading_date.py
  python3 next_trading_date.py --from-date 2026-05-22
"""

import argparse
from datetime import date

from market_time import next_trading_date


def main():
    parser = argparse.ArgumentParser(description="Print next regular US stock-market trading date.")
    parser.add_argument(
        "--from-date", help="Base date YYYY-MM-DD; output next trading date after it"
    )
    args = parser.parse_args()

    base = date.fromisoformat(args.from_date) if args.from_date else None
    print(next_trading_date(base).isoformat())


if __name__ == "__main__":
    main()
