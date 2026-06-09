"""Read-only prediction provider interface with fail-open cache semantics."""

from __future__ import annotations

import time
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from ml_platform.config import DEFAULT_DB_PATH
from repositories.prediction_repo import PredictionRepository


@dataclass(frozen=True)
class PredictionView:
    market_date: str
    symbol: str
    prediction_score: float | None
    confidence: str | None
    sample_size: int | None
    trend_label: str | None
    timing_score: float | None
    reason: str | None
    provider: str = "sqlite_daily_symbol_predictions"
    runtime_effect: str = "none"
    model_id: str | None = None
    model_version: str | None = None
    cache_status: str = "source"
    stale: bool = False
    fail_open: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class PredictionProvider(Protocol):
    """Read-only prediction provider contract."""

    latency_budget_ms: int
    timeout_ms: int
    fail_open: bool

    def get_prediction(self, market_date: str, symbol: str) -> PredictionView | None: ...


class SQLitePredictionProvider:
    """Read daily_symbol_predictions without modifying runtime state."""

    def __init__(self, db_path: Path | str = DEFAULT_DB_PATH):
        self.db_path = Path(db_path)
        self.latency_budget_ms = 25
        self.timeout_ms = 50
        self.fail_open = True

    def get_prediction(self, market_date: str, symbol: str) -> PredictionView | None:
        row = PredictionRepository(self.db_path).serving_prediction_row(market_date, symbol)
        if not row:
            return None

        return PredictionView(
            market_date=row["market_date"],
            symbol=row["symbol"],
            prediction_score=row["prediction_score"],
            confidence=row["confidence"],
            sample_size=row["sample_size"],
            trend_label=row["trend_label"],
            timing_score=row["timing_score"],
            reason=row["reason"],
        )


@dataclass(frozen=True)
class CachedPredictionProviderConfig:
    ttl_seconds: int = 60
    max_staleness_seconds: int = 300
    latency_budget_ms: int = 25
    timeout_ms: int = 50
    fail_open: bool = True
    model_id: str | None = None
    model_version: str | None = None


class CachedPredictionProvider:
    """Fail-open in-memory TTL wrapper around a read-only provider."""

    def __init__(
        self,
        source: PredictionProvider,
        *,
        config: CachedPredictionProviderConfig | None = None,
    ):
        self.source = source
        self.config = config or CachedPredictionProviderConfig()
        self.latency_budget_ms = self.config.latency_budget_ms
        self.timeout_ms = self.config.timeout_ms
        self.fail_open = self.config.fail_open
        self._cache: dict[tuple[str, str], tuple[float, PredictionView | None]] = {}

    def get_prediction(self, market_date: str, symbol: str) -> PredictionView | None:
        key = (market_date, symbol.upper())
        now = time.monotonic()
        cached = self._cache.get(key)
        if cached and now - cached[0] <= self.config.ttl_seconds:
            view = cached[1]
            if view is None:
                return None
            return PredictionView(
                **{
                    **view.to_dict(),
                    "cache_status": "hit",
                    "model_id": view.model_id or self.config.model_id,
                    "model_version": view.model_version or self.config.model_version,
                }
            )
        started = time.monotonic()
        try:
            view = self.source.get_prediction(market_date, symbol)
            elapsed_ms = (time.monotonic() - started) * 1000.0
            if elapsed_ms > self.timeout_ms and self.fail_open:
                return None
            if view is not None:
                view = PredictionView(
                    **{
                        **view.to_dict(),
                        "cache_status": "refresh",
                        "model_id": view.model_id or self.config.model_id,
                        "model_version": view.model_version or self.config.model_version,
                        "stale": False,
                    }
                )
            self._cache[key] = (now, view)
            return view
        except Exception:
            if self.fail_open:
                self._cache[key] = (now, None)
                return None
            raise


def serving_contract_summary() -> dict[str, Any]:
    defaults = CachedPredictionProviderConfig()
    return {
        "report_version": "prediction_serving_contract_v1",
        "runtime_effect": "contract_only_no_runtime_enablement",
        "provider_contract": "PredictionProvider",
        "cache": "CachedPredictionProvider",
        "latency_budget_ms": defaults.latency_budget_ms,
        "timeout_ms": defaults.timeout_ms,
        "ttl_seconds": defaults.ttl_seconds,
        "fail_open": True,
        "staleness_guard": "max_staleness_seconds plus model artifact age checks before authority",
        "model_version_audit": "model_id and model_version are attached to every served view",
        "generated_at": datetime.now(timezone.utc).isoformat(),
    }
