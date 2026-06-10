#!/usr/bin/env python3
"""Compatibility shim for the packaged auto-buy candidate manager."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SRC_DIR = ROOT_DIR / "src"
for path in (str(SRC_DIR), str(ROOT_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from trading_bot.signals.auto_buy import manager as _manager  # noqa: E402

if __name__ != "__main__":
    sys.modules[__name__] = _manager
else:
    main = _manager.main


if __name__ == "__main__":
    raise SystemExit(main())
