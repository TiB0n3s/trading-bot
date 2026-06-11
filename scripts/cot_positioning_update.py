#!/usr/bin/env python3
"""Normalize CFTC COT positioning data for market-context consumption.

This command intentionally reads a local JSON payload instead of fetching live
CFTC data. COT is weekly, publication-time sensitive data; fetch scheduling and
source mirroring should be handled by ops, while this script provides the
deterministic normalization contract used by the ML/context pipeline.
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

from market_intelligence.cot_positioning import DEFAULT_STATE_PATH, normalize_cot_state


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--input",
        required=True,
        help="JSON file containing CFTC financial-futures COT markets.",
    )
    parser.add_argument(
        "--output",
        default=str(DEFAULT_STATE_PATH),
        help="Normalized output path, default runtime_state/cot_positioning.json.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = ROOT / input_path
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path

    raw = json.loads(input_path.read_text())
    normalized = normalize_cot_state(raw, SYMBOL_CONFIG)

    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n")

    markets = ", ".join(sorted((normalized.get("markets") or {}).keys())) or "none"
    print(
        "Wrote COT positioning state "
        f"{output_path} markets={markets} mapped_symbols={len(normalized.get('symbol_map') or {})}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
