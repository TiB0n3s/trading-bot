"""Thin package entrypoint for operator checks."""

from __future__ import annotations

import sys

from trading_bot.ops_checks import legacy_cli as _legacy_cli

if __name__ != "__main__":
    sys.modules[__name__] = _legacy_cli
else:
    main = _legacy_cli.main


if __name__ == "__main__":
    raise SystemExit(main())
