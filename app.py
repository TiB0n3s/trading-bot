"""Compatibility shim for the packaged Flask runtime.

The runtime implementation lives in ``trading_bot.web.runtime_compat`` while
legacy deployment references such as ``gunicorn app:app`` continue to work.
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
SRC_DIR = ROOT_DIR / "src"
SCRIPTS_DIR = ROOT_DIR / "scripts"
for path in (str(SRC_DIR), str(SCRIPTS_DIR), str(ROOT_DIR)):
    if path not in sys.path:
        sys.path.insert(0, path)

from trading_bot.web import runtime_compat as _runtime_compat  # noqa: E402

if __name__ != "__main__":
    sys.modules[__name__] = _runtime_compat
else:
    create_app = _runtime_compat.create_app


if __name__ == "__main__":
    create_app(run_startup=True).run(host="0.0.0.0", port=5000, debug=False)
