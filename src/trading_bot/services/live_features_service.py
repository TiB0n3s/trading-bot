"""Live feature snapshot construction and persistence."""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Callable

import pytz
from feature_engine import compute_feature_snapshot
from macro_risk import get_macro_risk
from market_time import market_session
from prior_session_context import prior_session_context
from repositories.live_features_repo import LiveFeaturesRepository
from rolling_context import rolling_symbol_context
from services.canonical_bar_contract import (
    CANONICAL_BAR_ADJUSTMENT,
    CANONICAL_BAR_CONTRACT_VERSION,
    CANONICAL_BAR_REQUIRED_FIELDS,
    CANONICAL_BAR_TIMEFRAME,
    dataframe_to_canonical_bar_rows,
)
from services.market_data_service import market_data_service
from services.timescale_tick_writer_service import write_ticks_sync
from setup_engine import classify_feature_snapshot as classify_setup
from strategy_constants import SYMBOL_MARKET_ALIGNMENT
from symbols_config import APPROVED_SYMBOLS

ET = pytz.timezone("America/New_York")


class LiveFeaturesService:
    def __init__(
        self,
        *,
        repository: LiveFeaturesRepository,
        market_data,
        base_dir: Path,
        approved_symbols=frozenset(APPROVED_SYMBOLS),
        symbol_market_alignment: dict[str, Any] | None = None,
        logger: logging.Logger | None = None,
        macro_risk_provider: Callable[[Path], dict[str, Any]] = get_macro_risk,
        market_session_provider: Callable[[], str] = market_session,
        feature_snapshot_builder: Callable[..., dict[str, Any]] = compute_feature_snapshot,
        setup_classifier=classify_setup,
        rolling_context_provider: Callable[[str], dict[str, Any] | None] = rolling_symbol_context,
        prior_session_provider: Callable[[str], dict[str, Any] | None] = prior_session_context,
    ):
        self.repository = repository
        self.market_data = market_data
        self.base_dir = Path(base_dir)
        self.market_context_file = self.base_dir / "market_context.json"
        self.approved_symbols = set(approved_symbols)
        self.symbol_market_alignment = symbol_market_alignment or SYMBOL_MARKET_ALIGNMENT
        self.logger = logger or logging.getLogger(__name__)
        self.macro_risk_provider = macro_risk_provider
        self.market_session_provider = market_session_provider
        self.feature_snapshot_builder = feature_snapshot_builder
        self.setup_classifier = setup_classifier
        self.rolling_context_provider = rolling_context_provider
        self.prior_session_provider = prior_session_provider
        self._bar_cache: dict[tuple[str, str], tuple[list[float], list[float], str, int]] = {}
        self._bar_feed_used: dict[tuple[str, str], str] = {}

    def reset_bar_cache(self) -> None:
        self._bar_cache = {}
        self._bar_feed_used = {}

    def add_feature_audit_fields(self, snapshot: dict[str, Any]) -> dict[str, Any]:
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

    def build_degraded_snapshot(self, symbol: str, reason: str) -> dict[str, Any] | None:
        """Reuse the latest valid snapshot as explicit stale context for thin feeds."""
        latest = self.repository.latest_snapshot(symbol)
        if not latest:
            return None

        generated_at = datetime.now(ET).isoformat()
        previous_ts = latest.get("timestamp")
        latest["timestamp"] = generated_at
        latest["feature_generated_at"] = generated_at
        latest["feature_available_at"] = generated_at
        latest["source"] = "live_features_degraded_fallback"
        latest["is_stale"] = 1
        latest["staleness_reason"] = f"thin_feed_reused_previous_snapshot:{reason}"
        latest["feature_age_seconds"] = None
        latest["previous_snapshot_timestamp"] = previous_ts
        return latest

    def load_market_context(self) -> dict[str, Any]:
        if not self.market_context_file.exists():
            return {}
        try:
            return json.loads(self.market_context_file.read_text())
        except Exception as e:
            self.logger.warning(f"Could not parse market_context.json: {e}")
            return {}

    def benchmark_for(self, symbol: str) -> str:
        mapping = self.symbol_market_alignment.get(symbol) or {}
        return mapping.get("benchmark", "SPY")

    def recent_actions(self, symbol: str, limit: int = 10) -> list[str]:
        return self.repository.recent_actions(symbol, limit)

    def compute_trend(self, recent_actions_list: list[str]) -> dict[str, Any]:
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

    def trend_for(self, symbol: str) -> dict[str, Any]:
        return self.compute_trend(self.recent_actions(symbol))

    def get_bar_series(
        self,
        symbol: str,
        session: str,
        min_bars_needed: int = 16,
        target_bars: int = 30,
    ) -> tuple[list[float], list[float], str, int]:
        cache_key = (symbol, session)
        if cache_key in self._bar_cache:
            return self._bar_cache[cache_key]

        end = datetime.now(ET)

        timeframe = CANONICAL_BAR_TIMEFRAME
        lookbacks = (90, 180, 360)

        for window_minutes in lookbacks:
            start = end - timedelta(minutes=window_minutes)
            barset = self.market_data.get_barset_with_fallback(
                symbol,
                timeframe,
                start=start.isoformat(),
                end=end.isoformat(),
                adjustment=CANONICAL_BAR_ADJUSTMENT,
            )
            feed_used = self.market_data.get_feed_used(symbol) or "unknown"
            bars_payload = getattr(barset, "df", barset)
            rows = dataframe_to_canonical_bar_rows(
                bars_payload,
                symbol=symbol,
                feed=feed_used,
                adjusted=False,
            )
            rows = [
                row
                for row in rows
                if all(row.get(field) is not None for field in CANONICAL_BAR_REQUIRED_FIELDS)
            ]
            closes = [float(row["close"]) for row in rows]
            volumes = [float(row["volume"]) for row in rows]

            if len(closes) >= min_bars_needed:
                result = (
                    closes[-target_bars:],
                    volumes[-target_bars:],
                    timeframe,
                    len(closes),
                )
                self._bar_cache[cache_key] = result
                self._bar_feed_used[cache_key] = feed_used
                self.logger.info(
                    f"{symbol}: using {timeframe} bars ({feed_used}), "
                    f"got {len(closes)} bars from {window_minutes}m lookback"
                )
                return result

            self.logger.info(
                f"{symbol}: only {len(closes)} {timeframe} bars from {window_minutes}m lookback; retrying wider window"
            )

        raise RuntimeError(f"Not enough {timeframe} bars for {symbol} even after widened lookback")

    def build_snapshot(self, symbol: str) -> dict[str, Any]:
        symbol = symbol.upper().strip()
        if symbol not in self.approved_symbols:
            raise ValueError(f"{symbol} is not in APPROVED_SYMBOLS")

        session = self.market_session_provider()
        benchmark_symbol = self.benchmark_for(symbol)

        closes, volumes, timeframe, bar_count = self.get_bar_series(symbol, session=session)
        benchmark_closes, _, _, _ = self.get_bar_series(benchmark_symbol, session=session)

        ctx = self.load_market_context()
        symbol_ctx = (ctx.get("symbols") or {}).get(symbol) or {}
        macro = self.macro_risk_provider(self.base_dir)
        trend = self.trend_for(symbol)

        snapshot = self.feature_snapshot_builder(
            symbol=symbol,
            benchmark_symbol=benchmark_symbol,
            closes=closes,
            volumes=volumes,
            benchmark_closes=benchmark_closes,
            market_session=session,
            macro_regime=macro.get("macro_regime"),
            market_bias=symbol_ctx.get("bias"),
            trend_direction=trend.get("direction"),
            trend_strength=trend.get("strength"),
        )

        snapshot["timestamp"] = datetime.now(ET).isoformat()
        snapshot["bar_timeframe"] = timeframe
        snapshot["bar_count"] = bar_count
        snapshot["bar_feed_used"] = self._bar_feed_used.get((symbol, session), "sip")
        snapshot["bar_contract_version"] = CANONICAL_BAR_CONTRACT_VERSION
        snapshot["bar_required_fields"] = ",".join(CANONICAL_BAR_REQUIRED_FIELDS)

        if len(closes) >= 5:
            returns = []
            for prev, cur in zip(closes[-5:-1], closes[-4:]):
                if prev > 0:
                    returns.append((cur - prev) / prev * 100)
            if len(returns) >= 4:
                snapshot["momentum_acceleration_pct"] = round(
                    returns[-1] - (sum(returns[:-1]) / len(returns[:-1])),
                    4,
                )

        if len(volumes) >= 11:
            current_volume = float(volumes[-1] or 0)
            prior_volumes = [float(v or 0) for v in volumes[-11:-1]]
            usable = [v for v in prior_volumes if v > 0]
            if usable:
                avg_volume = sum(usable) / len(usable)
                if avg_volume > 0:
                    snapshot["volume_surge_ratio"] = round(current_volume / avg_volume, 3)

        try:
            rolling = self.rolling_context_provider(symbol) or {}
            snapshot["extension_from_recent_base_pct"] = rolling.get(
                "extension_from_recent_base_pct"
            )
        except Exception:
            snapshot["extension_from_recent_base_pct"] = None

        try:
            prior = self.prior_session_provider(symbol) or {}
            snapshot["prior_session_return_pct"] = prior.get("session_return_pct")
        except Exception:
            snapshot["prior_session_return_pct"] = None

        setup = self.setup_classifier(snapshot)
        snapshot["setup_label"] = setup.setup_label
        snapshot["setup_recommendation"] = setup.recommendation
        snapshot["setup_score"] = setup.setup_score
        snapshot["setup_confidence"] = setup.confidence
        snapshot["setup_key"] = setup.setup_key
        snapshot["setup_rationale"] = setup.rationale

        return self.add_feature_audit_fields(snapshot)

    def insert_snapshot(self, snapshot: dict[str, Any]) -> None:
        self.repository.insert_snapshot(snapshot)
        try:
            result = write_ticks_sync(
                [
                    {
                        "timestamp": snapshot.get("timestamp"),
                        "ticker": snapshot.get("symbol"),
                        "price": snapshot.get("last_price"),
                        "volume": snapshot.get("volume_ratio_5m") or 0,
                    }
                ]
            )
            if result.get("enabled") and not result.get("ok"):
                self.logger.warning(
                    "Timescale feature tick write failed: %s",
                    result.get("reason"),
                )
        except Exception as exc:
            self.logger.warning(f"Timescale feature tick write skipped: {exc}")

    def collect_all_symbols(self, write: bool = False, stdout: bool = False) -> tuple[int, int]:
        self.reset_bar_cache()

        success = 0
        failed = 0

        for symbol in sorted(self.approved_symbols):
            try:
                snapshot = self.build_snapshot(symbol)
            except RuntimeError as e:
                snapshot = self.build_degraded_snapshot(symbol, str(e))
                if snapshot is None:
                    failed += 1
                    self.logger.error(f"{symbol}: snapshot failed: {e}")
                    continue

                self.logger.warning(
                    "%s: using degraded stale feature snapshot because live bars were unavailable: %s",
                    symbol,
                    e,
                )

                if stdout:
                    print(json.dumps(snapshot, sort_keys=True))

                if write:
                    self.insert_snapshot(snapshot)

                success += 1
                self.logger.info(f"{symbol}: degraded snapshot collected")
            except Exception as e:
                failed += 1
                self.logger.error(f"{symbol}: snapshot failed: {e}")
            else:
                if stdout:
                    print(json.dumps(snapshot, sort_keys=True))

                if write:
                    self.insert_snapshot(snapshot)

                success += 1
                self.logger.info(f"{symbol}: snapshot collected")

        self.logger.info(f"feature snapshot collection complete: success={success} failed={failed}")
        return success, failed


def build_default_live_features_service(
    *,
    base_dir: Path,
    logger: logging.Logger | None = None,
) -> LiveFeaturesService:
    return LiveFeaturesService(
        repository=LiveFeaturesRepository(),
        market_data=market_data_service,
        base_dir=base_dir,
        logger=logger,
    )
