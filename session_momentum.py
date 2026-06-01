#!/usr/bin/env python3
"""
Session-aware intraday momentum tracker.

This module is now a compatibility and CLI entrypoint. Persistence lives in
repositories/session_momentum_repo.py and computation/market-data orchestration
lives in services/session_momentum_service.py.

Usage:
  python3 session_momentum.py --symbol NVDA
  python3 session_momentum.py --all
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path
from typing import Any


BASE_DIR = Path(__file__).resolve().parent
VENV_PYTHON = BASE_DIR / "venv" / "bin" / "python"
ENV_FILE = Path("/etc/trading-bot.env")


def reexec_under_venv_if_available() -> None:
    if not VENV_PYTHON.exists():
        return

    venv_dir = VENV_PYTHON.parent.parent.resolve()
    current_prefix = Path(sys.prefix).resolve()
    if current_prefix == venv_dir:
        return

    os.execv(
        str(VENV_PYTHON),
        [str(VENV_PYTHON), str(Path(__file__).resolve())] + sys.argv[1:],
    )


if __name__ == "__main__":
    reexec_under_venv_if_available()


def load_env_file(path: Path = ENV_FILE) -> bool:
    if not path.exists():
        return False

    for raw_line in path.read_text().splitlines():
        line = raw_line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue

        key, value = line.split("=", 1)
        key = key.strip()
        value = value.strip().strip('"').strip("'")
        if key and key not in os.environ:
            os.environ[key] = value

    return True


load_env_file()

from services.session_momentum_service import (  # noqa: E402
    LOOKBACK_MINUTES,
    MIN_BARS,
    SessionMomentumService,
    _bar_close,
    _bar_high,
    _bar_low,
    _bar_typical_price,
    _bar_volume,
    _compute_vwap,
    _is_strong_session,
    _merge_retained_strength,
    _pct_change,
    _safe_float,
    _window_return,
    classify_session_momentum,
    get_default_session_momentum_service,
)
from symbols_config import APPROVED_SYMBOLS_LIST  # noqa: E402


logger = logging.getLogger("session_momentum")


def init_session_momentum_table() -> None:
    get_default_session_momentum_service().init_table()


def build_session_momentum(api: Any, symbol: str) -> dict[str, Any]:
    return get_default_session_momentum_service().build(symbol)


def upsert_session_momentum(row: dict[str, Any]) -> None:
    get_default_session_momentum_service().upsert(row)


def get_latest_session_momentum(symbol: str) -> dict[str, Any] | None:
    return get_default_session_momentum_service().get_latest(symbol)


def refresh_symbol(api: Any, symbol: str) -> dict[str, Any]:
    return get_default_session_momentum_service().refresh_symbol(symbol)


def print_row(row: dict[str, Any]) -> None:
    SessionMomentumService.print_row(row)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="Refresh one symbol")
    parser.add_argument("--all", action="store_true", help="Refresh all approved symbols")
    args = parser.parse_args()

    if not args.symbol and not args.all:
        parser.error("Provide --symbol SYMBOL or --all")

    logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")

    service = get_default_session_momentum_service()
    symbols = APPROVED_SYMBOLS_LIST if args.all else [args.symbol.upper()]
    success = 0
    failed = 0

    for symbol in symbols:
        try:
            row = service.refresh_symbol(symbol)
            service.print_row(row)
            success += 1
        except Exception as e:
            failed += 1
            logger.error(f"session momentum refresh failed for {symbol}: {e}")

    print(f"rows_written: {success}")
    print(f"session_momentum_summary: success={success} failed={failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
