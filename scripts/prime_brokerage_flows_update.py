#!/usr/bin/env python3
"""Normalize prime brokerage / hedge-fund flow context for market_context.

The input is a locally supplied JSON payload from an approved external source.
This script does not scrape or authenticate against institutional feeds.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from symbols_config import SYMBOL_CONFIG

from market_intelligence.prime_brokerage_flows import (
    DEFAULT_STATE_PATH,
    normalize_prime_brokerage_state,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        required=True,
        help="JSON file containing sector/symbol prime brokerage flow metrics.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_STATE_PATH),
        help="Normalized output path, default runtime_state/prime_brokerage_flows.json.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = ROOT / input_path
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path

    raw = json.loads(input_path.read_text())
    normalized = normalize_prime_brokerage_state(raw, SYMBOL_CONFIG)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n")

    print(
        "Wrote prime brokerage flow state "
        f"{output_path} sectors={len(normalized.get('sectors') or {})} "
        f"symbols={len(normalized.get('symbols') or {})} "
        f"mapped_symbols={len(normalized.get('symbol_sector_map') or {})}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
