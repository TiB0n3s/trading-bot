#!/usr/bin/env python3
"""In-memory TTL cache for daily symbol predictions.

The webhook path must not query SQLite for model/prediction rows. This module
loads `daily_symbol_predictions` outside request handling and serves memory-only
lookups keyed by symbol.
"""

from __future__ import annotations

import argparse
import json
import logging
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from db import DB_PATH
from market_time import expected_market_context_date

logger = logging.getLogger(__name__)

PREDICTION_CACHE_TTL_SECONDS = int(os.getenv("PREDICTION_CACHE_TTL_SECONDS", "60"))
PREDICTION_CACHE_TARGET_MS = 25
PREDICTION_CACHE_HARD_TIMEOUT_MS = 50

_lock = threading.RLock()
_cache: dict[str, dict[str, Any]] = {}
_cache_market_date: str | None = None
_last_loaded_at: float | None = None
_last_load_duration_ms: float | None = None
_last_error: str | None = None
_loader_started = False
_loader_thread: threading.Thread | None = None


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _target_date(market_date: str | None = None) -> str:
    return market_date or expected_market_context_date().isoformat()


def load_predictions_from_db(
    *,
    market_date: str | None = None,
    db_path: Path | str = DB_PATH,
) -> dict[str, dict[str, Any]]:
    """Load all predictions for a date from SQLite.

    This function is intended for preload/background use, not webhook reads.
    """
    target_date = _target_date(market_date)
    db_path = Path(db_path)
    if not db_path.exists():
        return {}

    started = time.perf_counter()
    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True, timeout=0.05) as con:
        con.row_factory = sqlite3.Row
        exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='daily_symbol_predictions'"
        ).fetchone()
        if not exists:
            return {}
        rows = con.execute(
            """
            SELECT market_date, symbol, prediction_score, probability_of_profit,
                   probability_of_order, expected_pnl, confidence, sample_size,
                   reason, timing_score, recommended_entry_timing,
                   recommended_exit_timing, trend_score, trend_label,
                   trend_regime, trend_confidence, updated_at
            FROM daily_symbol_predictions
            WHERE market_date = ?
            """,
            (target_date,),
        ).fetchall()

    loaded = {}
    loaded_at = _now_iso()
    for row in rows:
        item = dict(row)
        symbol = str(item.pop("symbol") or "").upper()
        if not symbol:
            continue
        item["symbol"] = symbol
        item["cache_loaded_at"] = loaded_at
        item["provider"] = "daily_symbol_predictions_ttl_cache"
        item["runtime_effect"] = "observe_only_compare"
        loaded[symbol] = item

    duration_ms = (time.perf_counter() - started) * 1000.0
    if duration_ms > PREDICTION_CACHE_HARD_TIMEOUT_MS:
        logger.warning(
            "Prediction cache preload exceeded hard timeout: "
            f"{duration_ms:.1f}ms > {PREDICTION_CACHE_HARD_TIMEOUT_MS}ms"
        )
    return loaded


def refresh_prediction_cache(
    *,
    market_date: str | None = None,
    db_path: Path | str = DB_PATH,
) -> dict[str, Any]:
    global _cache, _cache_market_date, _last_loaded_at, _last_load_duration_ms, _last_error

    target_date = _target_date(market_date)
    started = time.perf_counter()
    try:
        loaded = load_predictions_from_db(market_date=target_date, db_path=db_path)
        duration_ms = (time.perf_counter() - started) * 1000.0
        with _lock:
            _cache = loaded
            _cache_market_date = target_date
            _last_loaded_at = time.time()
            _last_load_duration_ms = duration_ms
            _last_error = None
        logger.info(
            "Prediction cache refreshed: "
            f"market_date={target_date} symbols={len(loaded)} duration_ms={duration_ms:.1f}"
        )
    except Exception as e:
        duration_ms = (time.perf_counter() - started) * 1000.0
        with _lock:
            _last_error = str(e)
            _last_load_duration_ms = duration_ms
        logger.warning(f"Prediction cache refresh failed: {e}")

    return prediction_cache_status()


def start_prediction_cache_loader(
    *,
    market_date: str | None = None,
    db_path: Path | str = DB_PATH,
    ttl_seconds: int = PREDICTION_CACHE_TTL_SECONDS,
) -> None:
    """Start a daemon refresh loop. Safe to call multiple times."""
    global _loader_started, _loader_thread
    with _lock:
        if _loader_started:
            return
        _loader_started = True

    refresh_prediction_cache(market_date=market_date, db_path=db_path)

    def _loop() -> None:
        while True:
            time.sleep(max(1, ttl_seconds))
            refresh_prediction_cache(market_date=market_date, db_path=db_path)

    _loader_thread = threading.Thread(
        target=_loop,
        name="prediction-cache-loader",
        daemon=True,
    )
    _loader_thread.start()


def get_cached_prediction(symbol: str, *, market_date: str | None = None) -> dict[str, Any] | None:
    """Memory-only prediction lookup. Never refreshes or queries SQLite."""
    target_date = _target_date(market_date)
    symbol = (symbol or "").upper()
    with _lock:
        if target_date != _cache_market_date:
            return None
        prediction = _cache.get(symbol)
        return dict(prediction) if prediction else None


def prediction_cache_status() -> dict[str, Any]:
    with _lock:
        age_seconds = None if _last_loaded_at is None else max(0.0, time.time() - _last_loaded_at)
        stale = age_seconds is None or age_seconds > PREDICTION_CACHE_TTL_SECONDS * 2
        return {
            "enabled": True,
            "provider": "daily_symbol_predictions_ttl_cache",
            "market_date": _cache_market_date,
            "symbol_count": len(_cache),
            "last_loaded_at": (
                datetime.fromtimestamp(_last_loaded_at, timezone.utc).isoformat()
                if _last_loaded_at is not None
                else None
            ),
            "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
            "ttl_seconds": PREDICTION_CACHE_TTL_SECONDS,
            "target_latency_ms": PREDICTION_CACHE_TARGET_MS,
            "hard_timeout_ms": PREDICTION_CACHE_HARD_TIMEOUT_MS,
            "last_load_duration_ms": (
                round(_last_load_duration_ms, 3)
                if _last_load_duration_ms is not None
                else None
            ),
            "last_error": _last_error,
            "stale": stale,
            "runtime_effect": "observe_only_compare",
            "webhook_db_reads": False,
            "loader_started": _loader_started,
        }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preload", "status"))
    parser.add_argument("--date")
    parser.add_argument("--db-path", default=str(DB_PATH))
    args = parser.parse_args()

    if args.command == "preload":
        status = refresh_prediction_cache(market_date=args.date, db_path=args.db_path)
    else:
        status = prediction_cache_status()
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
