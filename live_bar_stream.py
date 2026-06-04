#!/usr/bin/env python3
"""Live 1-minute bar stream for session momentum and pattern learning."""

from __future__ import annotations

import argparse
import logging
import os
import sys
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
VENV_PYTHON = BASE_DIR / "venv" / "bin" / "python"
ENV_FILE = Path("/etc/trading-bot.env")


def reexec_under_venv_if_available() -> None:
    if not VENV_PYTHON.exists():
        return
    venv_dir = VENV_PYTHON.parent.parent.resolve()
    if Path(sys.prefix).resolve() == venv_dir:
        return
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve())] + sys.argv[1:])


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

from services.live_bar_stream_service import LiveBarStreamService  # noqa: E402
from symbols_config import APPROVED_SYMBOLS_LIST  # noqa: E402


def _symbols_from_args(args: argparse.Namespace) -> list[str]:
    symbols: list[str] = []
    for item in args.symbol or []:
        symbols.extend(part.strip().upper() for part in item.split(",") if part.strip())
    if args.all:
        symbols.extend(APPROVED_SYMBOLS_LIST)
    return sorted(set(symbols))


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", action="append", help="Symbol or comma-separated symbols")
    parser.add_argument("--all", action="store_true", help="Subscribe to all approved symbols")
    parser.add_argument(
        "--feed",
        default=os.getenv("ALPACA_BAR_STREAM_FEED", os.getenv("MARKET_DATA_BAR_FEED", "iex")),
        help="Alpaca data feed: iex for free paper accounts, sip for paid consolidated data",
    )
    parser.add_argument(
        "--gap-fill-minutes",
        type=int,
        default=int(os.getenv("LIVE_BAR_GAP_FILL_MINUTES", "90") or "90"),
    )
    args = parser.parse_args()

    symbols = _symbols_from_args(args)
    if not symbols:
        parser.error("Provide --symbol SYMBOL or --all")

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s - %(levelname)s - %(message)s",
        handlers=[
            logging.FileHandler(BASE_DIR / "live_bar_stream.log"),
            logging.StreamHandler(),
        ],
    )

    LiveBarStreamService(
        logger=logging.getLogger("live_bar_stream"),
        feed=args.feed,
        gap_fill_minutes=args.gap_fill_minutes,
    ).run(symbols)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
