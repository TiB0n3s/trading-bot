#!/usr/bin/env python3
"""Compatibility wrapper for the packaged auto-sell manager."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (ROOT, ROOT / "scripts", ROOT / "src"):
    path_s = str(path)
    if path_s not in sys.path:
        sys.path.insert(0, path_s)

from trading_bot.signals.auto_sell.manager import *  # noqa: F403
from trading_bot.signals.auto_sell.manager import main

if __name__ == "__main__":
    raise SystemExit(main())
