#!/usr/bin/env python3
"""Compatibility entrypoint for the Alpaca fill stream service.

The implementation lives in ``scripts.fill_stream``. This root shim preserves
the deployed systemd unit until it can be updated to call the scripts path.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_PATH = Path(__file__).resolve().parent / "scripts"
if str(SCRIPTS_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_PATH))

from scripts.fill_stream import main  # noqa: E402

__all__ = ["main"]


if __name__ == "__main__":
    main()
