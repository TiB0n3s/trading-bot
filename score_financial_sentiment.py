#!/usr/bin/env python3
"""Score financial text with the local fallback sentiment adapter."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from services.financial_sentiment_service import score_financial_text, score_financial_text_finbert


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--text")
    parser.add_argument("--file")
    parser.add_argument("--finbert", action="store_true")
    args = parser.parse_args()
    text = args.text or ""
    if args.file:
        text = Path(args.file).read_text()
    scorer = score_financial_text_finbert if args.finbert else score_financial_text
    print(json.dumps(scorer(text), indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
