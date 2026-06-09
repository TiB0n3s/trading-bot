"""Paper-only bridge from auto-buy discovery rows to canonical execution."""

from __future__ import annotations

import json
import logging
import os
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

from repositories.discovery_execution_bridge_repo import DiscoveryExecutionBridgeRepository
from services.auto_buy_execution_service import (
    AutoBuyBroker,
    build_auto_buy_execution_request,
    execute_auto_buy_order,
)

PENDING = "PENDING"
ROUTING = "ROUTING"
ROUTED = "ROUTED"
FAILED = "FAILED"
EXPIRED = "EXPIRED"


@dataclass(frozen=True)
class DiscoveryBridgeConfig:
    min_score: float = 13.0
    max_candidates_per_run: int = 3
    default_position_size_pct: float = 0.50
    stop_loss_pct: float = 1.00
    take_profit_pct: float = 2.00
    execution_mode: str = "paper"
    target_date: str | None = None
    max_candidate_age_seconds: int = 180
    symbol_cooldown_minutes: int = 45


@dataclass(frozen=True)
class DiscoveryBridgeResult:
    candidate_id: int
    symbol: str
    status: str
    routed_order_id: str | None = None
    reason: str | None = None


def bridge_enabled_from_env() -> bool:
    raw = os.getenv("DISCOVERY_EXECUTION_BRIDGE_ENABLED", "true").strip().lower()
    return raw in {"1", "true", "yes", "on"}


def bridge_config_from_env(*, target_date: str | None = None) -> DiscoveryBridgeConfig:
    return DiscoveryBridgeConfig(
        min_score=float(os.getenv("DISCOVERY_EXECUTION_BRIDGE_MIN_SCORE", "13")),
        max_candidates_per_run=int(os.getenv("DISCOVERY_EXECUTION_BRIDGE_MAX_PER_RUN", "3")),
        default_position_size_pct=float(os.getenv("AUTO_BUY_POSITION_SIZE_PCT", "0.50")),
        stop_loss_pct=float(os.getenv("AUTO_BUY_STOP_LOSS_PCT", "1.00")),
        take_profit_pct=float(os.getenv("AUTO_BUY_TAKE_PROFIT_PCT", "2.00")),
        execution_mode=os.getenv("EXECUTION_MODE", "paper"),
        target_date=target_date,
        max_candidate_age_seconds=int(
            os.getenv("DISCOVERY_EXECUTION_BRIDGE_MAX_AGE_SECONDS", "180")
        ),
        symbol_cooldown_minutes=int(
            os.getenv("DISCOVERY_EXECUTION_BRIDGE_SYMBOL_COOLDOWN_MINUTES", "45")
        ),
    )


def _paper_only_mode(execution_mode: str) -> bool:
    return str(execution_mode or "").strip().lower() in {"paper", "dry_run"}


def _et_cutoff_iso(delta: timedelta) -> str:
    return (datetime.now(ZoneInfo("America/New_York")) - delta).isoformat()


class DiscoveryExecutionBridgeService:
    """Claims strong candidates and routes them through canonical paper execution."""

    def __init__(
        self,
        *,
        broker: AutoBuyBroker,
        config: DiscoveryBridgeConfig | None = None,
        db_path: Path | str | None = None,
        repository: DiscoveryExecutionBridgeRepository | None = None,
        logger: logging.Logger | None = None,
    ):
        self.broker = broker
        self.config = config or DiscoveryBridgeConfig()
        self.repository = repository or DiscoveryExecutionBridgeRepository(db_path=db_path)
        self.logger = logger or logging.getLogger(__name__)

    def route_eligible_candidates(self) -> list[DiscoveryBridgeResult]:
        if not _paper_only_mode(self.config.execution_mode):
            return [
                DiscoveryBridgeResult(
                    candidate_id=0,
                    symbol="-",
                    status=FAILED,
                    reason=(
                        "discovery execution bridge is paper-only; "
                        f"execution_mode={self.config.execution_mode or 'unset'}"
                    ),
                )
            ]

        claimed = self.repository.claim_candidates(
            min_score=self.config.min_score,
            max_candidates=self.config.max_candidates_per_run,
            target_date=self.config.target_date,
            min_candidate_timestamp=_et_cutoff_iso(
                timedelta(seconds=self.config.max_candidate_age_seconds)
            ),
        )
        results: list[DiscoveryBridgeResult] = []
        for row in claimed:
            result = self._route_claimed_candidate(row)
            results.append(result)
        return results

    def _route_claimed_candidate(self, row: dict[str, Any]) -> DiscoveryBridgeResult:
        candidate_id = int(row["id"])
        symbol = str(row.get("symbol") or "").strip().upper()
        try:
            candidate = json.loads(row.get("candidate_json") or "{}")
            if not isinstance(candidate, dict):
                raise ValueError("candidate_json is not an object")
            cooldown_block = self._symbol_cooldown_block_reason(symbol)
            if cooldown_block:
                self.repository.mark_failed(candidate_id=candidate_id, reason=cooldown_block)
                self._log_drop(candidate_id=candidate_id, symbol=symbol, reason=cooldown_block)
                return DiscoveryBridgeResult(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    status=FAILED,
                    reason=cooldown_block,
                )
            live_block = self._broker_state_block_reason(symbol)
            if live_block:
                self.repository.mark_failed(candidate_id=candidate_id, reason=live_block)
                self._log_drop(candidate_id=candidate_id, symbol=symbol, reason=live_block)
                return DiscoveryBridgeResult(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    status=FAILED,
                    reason=live_block,
                )

            request = build_auto_buy_execution_request(
                candidate=candidate,
                default_position_size_pct=self.config.default_position_size_pct,
                stop_loss_pct=self.config.stop_loss_pct,
                take_profit_pct=self.config.take_profit_pct,
                client_order_id_factory=lambda order_symbol: (
                    f"auto-bridge-{candidate_id}-{order_symbol}"
                ),
            )
            outcome = execute_auto_buy_order(request, self.broker)
            if outcome.submitted and outcome.order:
                order_id = _order_identifier(outcome.order)
                self.repository.mark_routed(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    order_id=order_id,
                    order=outcome.order,
                )
                return DiscoveryBridgeResult(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    status=ROUTED,
                    routed_order_id=order_id,
                )

            reason = outcome.live_block_reason or outcome.failure_reason or "order not submitted"
            self.repository.mark_failed(candidate_id=candidate_id, reason=reason)
            return DiscoveryBridgeResult(
                candidate_id=candidate_id,
                symbol=symbol,
                status=FAILED,
                reason=reason,
            )
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            self.repository.mark_failed(candidate_id=candidate_id, reason=reason)
            return DiscoveryBridgeResult(
                candidate_id=candidate_id,
                symbol=symbol,
                status=FAILED,
                reason=reason,
            )

    def _symbol_cooldown_block_reason(self, symbol: str) -> str | None:
        if self.config.symbol_cooldown_minutes <= 0:
            return None
        recent_route_cutoff = _et_cutoff_iso(timedelta(minutes=self.config.symbol_cooldown_minutes))
        recent = self.repository.latest_recent_routed_candidate(
            symbol=symbol,
            recent_route_cutoff=recent_route_cutoff,
        )
        if not recent:
            return None
        order_id = recent.get("routed_order_id") or recent.get("order_id") or "-"
        return (
            "bridge blocked: symbol cooldown active "
            f"for {symbol}; prior_candidate_id={recent.get('id')} "
            f"prior_order_id={order_id} prior_timestamp={recent.get('candidate_timestamp')}"
        )

    def _broker_state_block_reason(self, symbol: str) -> str | None:
        position_getter = getattr(self.broker, "get_position", None)
        if callable(position_getter):
            try:
                position = position_getter(symbol)
            except Exception as exc:
                return f"bridge blocked: broker position check failed: {type(exc).__name__}: {exc}"
            if _position_has_qty(position):
                return f"bridge blocked: existing open position for {symbol}"

        order_lister = getattr(self.broker, "list_open_orders", None)
        if callable(order_lister):
            try:
                open_orders = order_lister(symbol)
            except Exception as exc:
                return (
                    f"bridge blocked: broker open-order check failed: {type(exc).__name__}: {exc}"
                )
            if open_orders:
                return f"bridge blocked: existing open order for {symbol}"

        return None

    def _log_drop(self, *, candidate_id: int, symbol: str, reason: str) -> None:
        self.logger.info(
            "discovery_execution_bridge_drop candidate_id=%s symbol=%s reason=%s",
            candidate_id,
            symbol,
            reason,
        )


def _order_identifier(order: dict[str, Any]) -> str | None:
    for key in ("order_id", "id", "client_order_id"):
        value = order.get(key)
        if value:
            return str(value)
    return None


def _position_has_qty(position: Any) -> bool:
    if position is None:
        return False
    if isinstance(position, dict):
        qty = position.get("qty") or position.get("quantity")
    else:
        qty = getattr(position, "qty", None) or getattr(position, "quantity", None)
    try:
        return abs(float(qty)) > 0
    except (TypeError, ValueError):
        return bool(position)
