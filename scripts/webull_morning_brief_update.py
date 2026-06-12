#!/usr/bin/env python3
"""Normalize a Webull morning brief JSON payload for market_context."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))

from market_intelligence.webull_morning_brief import (  # noqa: E402
    DEFAULT_STATE_PATH,
    normalize_webull_morning_brief_state,
)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Raw Webull morning brief JSON payload.")
    parser.add_argument(
        "--output",
        default=str(DEFAULT_STATE_PATH),
        help="Normalized output path, default runtime_state/webull_morning_brief.json.",
    )
    args = parser.parse_args()

    input_path = Path(args.input)
    if not input_path.is_absolute():
        input_path = ROOT / input_path
    output_path = Path(args.output)
    if not output_path.is_absolute():
        output_path = ROOT / output_path

    normalized = normalize_webull_morning_brief_state(json.loads(input_path.read_text()))
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(json.dumps(normalized, indent=2, sort_keys=True) + "\n")
    print(
        f"Wrote Webull morning brief state {output_path} "
        f"available={normalized.get('available')} symbols={len(normalized.get('symbols') or {})}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
