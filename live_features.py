#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import logging
import os
import sys
from datetime import datetime
from pathlib import Path

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

    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve())] + sys.argv[1:])


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

import pytz

from strategy_constants import SYMBOL_MARKET_ALIGNMENT
from market_time import is_trading_day, now_et
from services.live_features_service import build_default_live_features_service

logger = logging.getLogger("live_features")
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)

MARKET_CONTEXT_FILE = BASE_DIR / "market_context.json"
ET = pytz.timezone("America/New_York")
_live_features_service = None


def get_live_features_service():
    global _live_features_service
    if _live_features_service is None:
        _live_features_service = build_default_live_features_service(
            base_dir=BASE_DIR,
            logger=logger,
        )
    return _live_features_service


def add_feature_audit_fields(snapshot: dict) -> dict:
    """Attach leakage/audit metadata for dataset exports."""
    generated_at = datetime.now(ET).isoformat()
    feature_time = snapshot.get("timestamp") or generated_at
    snapshot["feature_generated_at"] = generated_at
    snapshot["feature_available_at"] = generated_at
    snapshot["feature_age_seconds"] = 0.0
    snapshot["source"] = "live_features"
    snapshot["is_stale"] = 0
    snapshot["staleness_reason"] = None
    if not snapshot.get("timestamp"):
        snapshot["timestamp"] = feature_time
        snapshot["is_stale"] = 1
        snapshot["staleness_reason"] = "missing_snapshot_timestamp"
    return snapshot

def load_market_context() -> dict:
    if not MARKET_CONTEXT_FILE.exists():
        return {}
    try:
        return json.loads(MARKET_CONTEXT_FILE.read_text())
    except Exception as e:
        logger.warning(f"Could not parse market_context.json: {e}")
        return {}


def benchmark_for(symbol: str) -> str:
    mapping = SYMBOL_MARKET_ALIGNMENT.get(symbol) or {}
    return mapping.get("benchmark", "SPY")


def recent_actions(symbol: str, limit: int = 10) -> list[str]:
    return get_live_features_service().recent_actions(symbol, limit)


def compute_trend(recent_actions_list: list[str]) -> dict:
    if not recent_actions_list:
        return {
            "direction": "neutral",
            "strength": "weak",
            "consecutive_count": 0,
            "last_signal": None,
        }

    first = recent_actions_list[0]
    count = 0
    for action in recent_actions_list:
        if action == first:
            count += 1
        else:
            break

    direction = ("bullish" if first == "buy" else "bearish") if count >= 3 else "neutral"
    strength = "confirmed" if count >= 5 else "developing" if count >= 3 else "weak"

    return {
        "direction": direction,
        "strength": strength,
        "consecutive_count": count,
        "last_signal": first,
    }


def trend_for(symbol: str) -> dict:
    return compute_trend(recent_actions(symbol))


def get_bar_series(
    symbol: str,
    session: str,
    min_bars_needed: int = 16,
    target_bars: int = 30,
) -> tuple[list[float], list[float], str, int]:
    return get_live_features_service().get_bar_series(
        symbol,
        session=session,
        min_bars_needed=min_bars_needed,
        target_bars=target_bars,
    )


def build_snapshot(symbol: str) -> dict:
    return get_live_features_service().build_snapshot(symbol)

def insert_snapshot(snapshot: dict) -> None:
    get_live_features_service().insert_snapshot(snapshot)

def collect_all_symbols(write: bool = False, stdout: bool = False) -> tuple[int, int]:
    return get_live_features_service().collect_all_symbols(write=write, stdout=stdout)

def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--symbol", help="Approved symbol, e.g. QQQ")
    parser.add_argument("--all-symbols", action="store_true", help="Collect snapshots for all approved symbols")
    parser.add_argument("--stdout", action="store_true", help="Print JSON snapshot(s)")
    parser.add_argument("--write", action="store_true", help="Insert snapshot(s) into feature_snapshots")
    args = parser.parse_args()

    if not args.symbol and not args.all_symbols:
        parser.error("Must provide either --symbol or --all-symbols")

    if args.symbol and args.all_symbols:
        parser.error("Use either --symbol or --all-symbols, not both")

    if not is_trading_day(now_et().date()):
        logger.info("Skipping live feature collection: today is not a trading day")
        return 0

    if args.all_symbols:
        success, failed = collect_all_symbols(write=args.write, stdout=args.stdout)
        return 0 if success > 0 and failed == 0 else 1

    try:
        snapshot = build_snapshot(args.symbol)
    except Exception as e:
        logger.error(f"Failed to build snapshot for {args.symbol}: {e}")
        return 1

    if args.stdout or not args.write:
        print(json.dumps(snapshot, indent=2, sort_keys=True))

    if args.write:
        insert_snapshot(snapshot)
        logger.info(
            f"Inserted feature snapshot for {snapshot['symbol']} at {snapshot['timestamp']}"
        )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
