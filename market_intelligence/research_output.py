#!/usr/bin/env python3
"""
Research output helpers.

Small helpers for writing raw research JSON safely.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any


def write_raw_research(raw: dict[str, Any], output_path: str | Path) -> None:
    path = Path(output_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(raw, indent=2, sort_keys=True) + "\n")


def raw_research_summary(raw: dict[str, Any]) -> dict[str, Any]:
    symbols = raw.get("symbols") or {}
    return {
        "market_date": raw.get("market_date"),
        "macro_sentiment": raw.get("macro_sentiment"),
        "macro_regime": raw.get("macro_regime"),
        "symbols": len(symbols),
        "has_index_state": isinstance(raw.get("index_state"), dict),
        "has_sector_state": isinstance(raw.get("sector_state"), dict),
        "macro_events": len(raw.get("macro_events") or []),
    }
