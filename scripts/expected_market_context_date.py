#!/usr/bin/env python3
"""Print the market context date expected for the current session."""

from __future__ import annotations

import argparse
from datetime import date

from market_time import expected_market_context_date


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Print same-day trading context date, or next session on non-trading days."
    )
    parser.add_argument("--from-date", help="Base date YYYY-MM-DD; defaults to current ET date")
    args = parser.parse_args()

    base = date.fromisoformat(args.from_date) if args.from_date else None
    print(expected_market_context_date(base).isoformat())


if __name__ == "__main__":
    main()
