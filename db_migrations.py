#!/usr/bin/env python3
"""Compatibility entrypoint for the SQLite migration runner.

The implementation lives in ``scripts.db_migrations``. This root shim preserves
systemd, docs, and legacy imports that still call ``python db_migrations.py``.
"""

from __future__ import annotations

import sys
from pathlib import Path

SCRIPTS_PATH = Path(__file__).resolve().parent / "scripts"
if str(SCRIPTS_PATH) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_PATH))

from scripts.db_migrations import MIGRATIONS, Migration, apply_migration, main, status  # noqa: E402

__all__ = [
    "MIGRATIONS",
    "Migration",
    "apply_migration",
    "main",
    "status",
]


if __name__ == "__main__":
    raise SystemExit(main())
