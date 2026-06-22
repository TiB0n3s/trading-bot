"""In-memory TTL cache for daily symbol predictions."""

from __future__ import annotations

import logging
import threading
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable

from market_time import expected_market_context_date
from repositories.prediction_repo import PredictionRepository

SCORE_CLIP_MIN = 0.0
SCORE_CLIP_MAX = 100.0
PREDICTION_SCORE_FIELDS = (
    "prediction_score",
    "timing_score",
    "trend_score",
    "ml_prediction_score",
)
PROBABILITY_FIELDS = (
    "probability_of_profit",
    "expected_win_rate",
)


def now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _clip_float(value: Any, *, low: float, high: float) -> tuple[Any, bool]:
    if value is None:
        return None, False
    try:
        numeric = float(value)
    except Exception:
        return value, False
    clipped = max(low, min(high, numeric))
    return clipped, clipped != numeric


def sanitize_prediction_outputs(item: dict[str, Any]) -> dict[str, Any]:
    """Hard-clip prediction outputs before they can enter runtime context."""
    sanitized = dict(item)
    clipped_fields = []
    for field in PREDICTION_SCORE_FIELDS:
        if field in sanitized:
            sanitized[field], clipped = _clip_float(
                sanitized.get(field),
                low=SCORE_CLIP_MIN,
                high=SCORE_CLIP_MAX,
            )
            if clipped:
                clipped_fields.append(field)
    for field in PROBABILITY_FIELDS:
        if field in sanitized:
            sanitized[field], clipped = _clip_float(
                sanitized.get(field),
                low=0.0,
                high=1.0,
            )
            if clipped:
                clipped_fields.append(field)
    if clipped_fields:
        sanitized["prediction_output_clipped"] = True
        sanitized["prediction_output_clipped_fields"] = clipped_fields
        sanitized["prediction_output_clip_bounds"] = {
            "score": [SCORE_CLIP_MIN, SCORE_CLIP_MAX],
            "probability": [0.0, 1.0],
        }
    else:
        sanitized.setdefault("prediction_output_clipped", False)
    return sanitized


class PredictionCacheService:
    def __init__(
        self,
        *,
        repository_factory: Callable[[Path | str | None], PredictionRepository],
        ttl_seconds: int,
        target_latency_ms: int,
        hard_timeout_ms: int,
        logger: logging.Logger | None = None,
        expected_date_provider=expected_market_context_date,
    ):
        self.repository_factory = repository_factory
        self.ttl_seconds = ttl_seconds
        self.target_latency_ms = target_latency_ms
        self.hard_timeout_ms = hard_timeout_ms
        self.logger = logger or logging.getLogger(__name__)
        self.expected_date_provider = expected_date_provider
        self._lock = threading.RLock()
        self._cache: dict[str, dict[str, Any]] = {}
        self._cache_market_date: str | None = None
        self._last_loaded_at: float | None = None
        self._last_load_duration_ms: float | None = None
        self._last_error: str | None = None
        self._loader_started = False
        self._loader_thread: threading.Thread | None = None

    def target_date(self, market_date: str | None = None) -> str:
        return market_date or self.expected_date_provider().isoformat()

    def load_predictions_from_db(
        self,
        *,
        market_date: str | None = None,
        db_path: Path | str | None = None,
    ) -> dict[str, dict[str, Any]]:
        target_date = self.target_date(market_date)
        started = time.perf_counter()
        rows = self.repository_factory(db_path).daily_predictions(target_date)

        loaded = {}
        loaded_at = now_iso()
        for row in rows:
            item = sanitize_prediction_outputs(dict(row))
            symbol = str(item.pop("symbol") or "").upper()
            if not symbol:
                continue
            item["symbol"] = symbol
            item["prediction_generated_at"] = item.get("prediction_generated_at")
            item["cache_loaded_at"] = loaded_at
            item["provider"] = "daily_symbol_predictions_ttl_cache"
            item["runtime_effect"] = "observe_only_compare"
            loaded[symbol] = item

        duration_ms = (time.perf_counter() - started) * 1000.0
        if duration_ms > self.hard_timeout_ms:
            self.logger.warning(
                "Prediction cache preload exceeded hard timeout: "
                f"{duration_ms:.1f}ms > {self.hard_timeout_ms}ms"
            )
        return loaded

    def refresh(
        self,
        *,
        market_date: str | None = None,
        db_path: Path | str | None = None,
    ) -> dict[str, Any]:
        target_date = self.target_date(market_date)
        started = time.perf_counter()
        try:
            loaded = self.load_predictions_from_db(
                market_date=target_date,
                db_path=db_path,
            )
            duration_ms = (time.perf_counter() - started) * 1000.0
            with self._lock:
                self._cache = loaded
                self._cache_market_date = target_date
                self._last_loaded_at = time.time()
                self._last_load_duration_ms = duration_ms
                self._last_error = None
            self.logger.info(
                "Prediction cache refreshed: "
                f"market_date={target_date} symbols={len(loaded)} duration_ms={duration_ms:.1f}"
            )
        except Exception as e:
            duration_ms = (time.perf_counter() - started) * 1000.0
            with self._lock:
                self._last_error = str(e)
                self._last_load_duration_ms = duration_ms
            self.logger.warning(f"Prediction cache refresh failed: {e}")

        return self.status()

    def start_loader(
        self,
        *,
        market_date: str | None = None,
        db_path: Path | str | None = None,
        ttl_seconds: int | None = None,
    ) -> None:
        with self._lock:
            if self._loader_started:
                return
            self._loader_started = True

        ttl_seconds = ttl_seconds if ttl_seconds is not None else self.ttl_seconds
        self.refresh(market_date=market_date, db_path=db_path)

        def _loop() -> None:
            while True:
                time.sleep(max(1, ttl_seconds))
                self.refresh(market_date=market_date, db_path=db_path)

        self._loader_thread = threading.Thread(
            target=_loop,
            name="prediction-cache-loader",
            daemon=True,
        )
        self._loader_thread.start()

    def get_cached_prediction(
        self,
        symbol: str,
        *,
        market_date: str | None = None,
    ) -> dict[str, Any] | None:
        target_date = self.target_date(market_date)
        symbol = (symbol or "").upper()
        with self._lock:
            if target_date != self._cache_market_date:
                return None
            # Staleness gate: if the background loader is wedged or was never
            # started, do NOT serve hours-old predictions. Fail open to "no
            # prediction" (None) so the downstream gate treats ML as absent
            # rather than authoritative. Threshold mirrors status().
            if self._last_loaded_at is None or (
                time.time() - self._last_loaded_at
            ) > self.ttl_seconds * 2:
                return None
            prediction = self._cache.get(symbol)
            return dict(prediction) if prediction else None

    def status(self) -> dict[str, Any]:
        with self._lock:
            age_seconds = (
                None
                if self._last_loaded_at is None
                else max(0.0, time.time() - self._last_loaded_at)
            )
            stale = age_seconds is None or age_seconds > self.ttl_seconds * 2
            return {
                "enabled": True,
                "provider": "daily_symbol_predictions_ttl_cache",
                "market_date": self._cache_market_date,
                "symbol_count": len(self._cache),
                "last_loaded_at": (
                    datetime.fromtimestamp(self._last_loaded_at, timezone.utc).isoformat()
                    if self._last_loaded_at is not None
                    else None
                ),
                "age_seconds": round(age_seconds, 3) if age_seconds is not None else None,
                "ttl_seconds": self.ttl_seconds,
                "target_latency_ms": self.target_latency_ms,
                "hard_timeout_ms": self.hard_timeout_ms,
                "last_load_duration_ms": (
                    round(self._last_load_duration_ms, 3)
                    if self._last_load_duration_ms is not None
                    else None
                ),
                "last_error": self._last_error,
                "stale": stale,
                "runtime_effect": "observe_only_compare",
                "webhook_db_reads": False,
                "loader_started": self._loader_started,
            }
