"""Compatibility namespace for packaged services."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
SCRIPTS_DIR = ROOT_DIR / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from trading_bot import services as _services

__path__ = _services.__path__
__all__ = getattr(_services, "__all__", ())
