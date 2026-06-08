#!/usr/bin/env python3
"""Compatibility entrypoint for operator checks.

The implementation lives in ``trading_bot.ops_checks.cli``. Keep this root
shim so cron, runbooks, and operator muscle memory can continue to use:

    python3 ops_check.py <command>
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
SCRIPTS_DIR = ROOT_DIR / "scripts"
for path in (str(SCRIPTS_DIR), str(SRC_DIR), str(ROOT_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from trading_bot.ops_checks import cli as _cli  # noqa: E402

if __name__ != "__main__":
    sys.modules[__name__] = _cli
else:
    main = _cli.main


if __name__ == "__main__":
    raise SystemExit(main())
