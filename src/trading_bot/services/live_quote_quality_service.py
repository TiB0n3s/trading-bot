"""Live quote quality diagnostics across configured market-data providers."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any

from services.market_data_parity_service import MarketDataParityService

LIVE_QUOTE_QUALITY_VERSION = "live_quote_quality_v1"
LIVE_QUOTE_QUALITY_RUNTIME_EFFECT = "diagnostic_only_no_live_authority"


@dataclass(frozen=True)
class LiveQuoteQualityThresholds:
    min_available_providers: int = 2
    max_mid_range_pct: float = 0.35
    max_provider_spread_pct: float = 0.50


@dataclass(frozen=True)
class LiveQuoteQualityReport:
    version: str
    runtime_effect: str
    symbol: str
    status: str
    available_provider_count: int
    available_providers: list[str]
    unavailable_providers: list[str]
    mid_range_pct: float | None
    max_provider_spread_pct: float | None
    thresholds: dict[str, Any]
    blockers: list[str] = field(default_factory=list)
    provider_errors: dict[str, str] = field(default_factory=dict)
    parity_payload: dict[str, Any] = field(default_factory=dict)

    @property
    def ok(self) -> bool:
        return self.status == "ok"

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["ok"] = self.ok
        return payload


class LiveQuoteQualityService:
    def __init__(
        self,
        parity_service: MarketDataParityService,
        thresholds: LiveQuoteQualityThresholds | None = None,
    ):
        self.parity_service = parity_service
        self.thresholds = thresholds or LiveQuoteQualityThresholds()

    def assess(self, symbol: str) -> LiveQuoteQualityReport:
        symbol = str(symbol or "").upper().strip()
        payload = self.parity_service.latest_quote_provider_parity(symbol)
        providers = payload.get("providers") or {}
        available = [
            name
            for name, row in providers.items()
            if isinstance(row, dict) and bool(row.get("available"))
        ]
        unavailable = sorted(set(providers) - set(available))
        provider_spreads = [
            float(row["spread_pct"])
            for row in providers.values()
            if isinstance(row, dict) and row.get("spread_pct") is not None
        ]
        max_spread = max(provider_spreads) if provider_spreads else None
        mid_range_pct = payload.get("mid_range_pct")
        mid_range_pct = float(mid_range_pct) if mid_range_pct is not None else None

        blockers: list[str] = []
        if len(available) < self.thresholds.min_available_providers:
            blockers.append(
                f"available_provider_count_below_{self.thresholds.min_available_providers}"
            )
        if mid_range_pct is not None and mid_range_pct > self.thresholds.max_mid_range_pct:
            blockers.append("provider_mid_range_too_wide")
        if max_spread is not None and max_spread > self.thresholds.max_provider_spread_pct:
            blockers.append("provider_spread_too_wide")

        provider_errors = {
            key.replace("_error", ""): str(value)
            for key, value in payload.items()
            if key.endswith("_error") and value
        }
        return LiveQuoteQualityReport(
            version=LIVE_QUOTE_QUALITY_VERSION,
            runtime_effect=LIVE_QUOTE_QUALITY_RUNTIME_EFFECT,
            symbol=symbol,
            status="ok" if not blockers else "warn",
            available_provider_count=len(available),
            available_providers=sorted(available),
            unavailable_providers=unavailable,
            mid_range_pct=mid_range_pct,
            max_provider_spread_pct=max_spread,
            thresholds=asdict(self.thresholds),
            blockers=blockers,
            provider_errors=provider_errors,
            parity_payload=payload,
        )
