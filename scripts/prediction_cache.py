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
from pathlib import Path
from typing import Any

from repositories.prediction_repo import PredictionRepository
from services.prediction_cache_service import PredictionCacheService

logger = logging.getLogger(__name__)

PREDICTION_CACHE_TTL_SECONDS = int(os.getenv("PREDICTION_CACHE_TTL_SECONDS", "60"))
PREDICTION_CACHE_TARGET_MS = 25
PREDICTION_CACHE_HARD_TIMEOUT_MS = 50

_prediction_cache_service: PredictionCacheService | None = None


def get_prediction_cache_service() -> PredictionCacheService:
    global _prediction_cache_service
    if _prediction_cache_service is None:
        _prediction_cache_service = PredictionCacheService(
            repository_factory=lambda db_path: PredictionRepository(db_path),
            ttl_seconds=PREDICTION_CACHE_TTL_SECONDS,
            target_latency_ms=PREDICTION_CACHE_TARGET_MS,
            hard_timeout_ms=PREDICTION_CACHE_HARD_TIMEOUT_MS,
            logger=logger,
        )
    return _prediction_cache_service


def load_predictions_from_db(
    *,
    market_date: str | None = None,
    db_path: Path | str | None = None,
) -> dict[str, dict[str, Any]]:
    """Load all predictions for a date from SQLite.

    This function is intended for preload/background use, not webhook reads.
    """
    return get_prediction_cache_service().load_predictions_from_db(
        market_date=market_date,
        db_path=db_path,
    )


def refresh_prediction_cache(
    *,
    market_date: str | None = None,
    db_path: Path | str | None = None,
) -> dict[str, Any]:
    return get_prediction_cache_service().refresh(
        market_date=market_date,
        db_path=db_path,
    )


def start_prediction_cache_loader(
    *,
    market_date: str | None = None,
    db_path: Path | str | None = None,
    ttl_seconds: int = PREDICTION_CACHE_TTL_SECONDS,
) -> None:
    """Start a daemon refresh loop. Safe to call multiple times."""
    get_prediction_cache_service().start_loader(
        market_date=market_date,
        db_path=db_path,
        ttl_seconds=ttl_seconds,
    )


def get_cached_prediction(symbol: str, *, market_date: str | None = None) -> dict[str, Any] | None:
    """Memory-only prediction lookup. Never refreshes or queries SQLite."""
    return get_prediction_cache_service().get_cached_prediction(
        symbol,
        market_date=market_date,
    )


def prediction_cache_status() -> dict[str, Any]:
    return get_prediction_cache_service().status()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("command", choices=("preload", "status"))
    parser.add_argument("--date")
    parser.add_argument("--db-path")
    args = parser.parse_args()

    if args.command == "preload":
        status = refresh_prediction_cache(market_date=args.date, db_path=args.db_path)
    else:
        status = prediction_cache_status()
    print(json.dumps(status, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
