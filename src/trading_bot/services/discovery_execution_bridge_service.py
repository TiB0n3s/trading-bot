"""Paper-only bridge from auto-buy discovery rows to canonical execution."""

from __future__ import annotations

import json
import logging
import os
import sys
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

ROOT_DIR = Path(__file__).resolve().parents[3]
if str(ROOT_DIR) in sys.path:
    sys.path.remove(str(ROOT_DIR))
sys.path.insert(0, str(ROOT_DIR))

from repositories.discovery_execution_bridge_repo import DiscoveryExecutionBridgeRepository
from services.auto_buy_execution_service import (
    AutoBuyBroker,
    build_auto_buy_execution_request,
    execute_auto_buy_order,
)

from config.conviction import load_conviction_config
from trading_bot.signals.conviction.policy import (
    conviction_active_for_mode,
    conviction_entry_decision,
)

PENDING = "PENDING"
ROUTING = "ROUTING"
ROUTED = "ROUTED"
FAILED = "FAILED"
EXPIRED = "EXPIRED"

REASON_CODE_COOLDOWN_ACTIVE = "cooldown_active"
REASON_CODE_OPEN_POSITION_EXISTS = "open_position_exists"
REASON_CODE_OPEN_ORDER_EXISTS = "open_order_exists"
REASON_CODE_POSITION_CHECK_FAILED = "position_check_failed"
REASON_CODE_OPEN_ORDER_CHECK_FAILED = "open_order_check_failed"
REASON_CODE_MISSING_CANONICAL_TRACE = "missing_canonical_trace"
REASON_CODE_BROKER_REJECTED_ORDER = "broker_rejected_order"
REASON_CODE_BROKER_TRANSIENT_FAILURE = "broker_transient_failure"
REASON_CODE_CANDIDATE_DECODE_FAILED = "candidate_decode_failed"
REASON_CODE_ALLOCATION_ROUNDS_TO_ZERO = "allocation_rounds_to_zero"
REASON_CODE_CONVICTION_ENTRY_BLOCK = "conviction_entry_block"

_CONVICTION_CFG = load_conviction_config()


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
    min_trade_qty: float = 1.0
    allow_fractional_shares: bool = False


@dataclass(frozen=True)
class DiscoveryBridgeResult:
    candidate_id: int
    symbol: str
    status: str
    routed_order_id: str | None = None
    reason: str | None = None
    reason_code: str | None = None


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
        min_trade_qty=float(os.getenv("DISCOVERY_EXECUTION_BRIDGE_MIN_TRADE_QTY", "1")),
        allow_fractional_shares=os.getenv(
            "DISCOVERY_EXECUTION_BRIDGE_ALLOW_FRACTIONAL_SHARES", "false"
        )
        .strip()
        .lower()
        in {"1", "true", "yes", "on"},
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
            cooldown_block = self._symbol_cooldown_block(symbol)
            if cooldown_block:
                reason_code, reason = cooldown_block
                self.repository.mark_failed(candidate_id=candidate_id, reason=reason)
                self._log_drop(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    reason_code=reason_code,
                    reason_detail=reason,
                )
                return DiscoveryBridgeResult(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    status=FAILED,
                    reason=reason,
                    reason_code=reason_code,
                )
            live_block = self._broker_state_block(symbol)
            if live_block:
                reason_code, reason = live_block
                self.repository.mark_failed(candidate_id=candidate_id, reason=reason)
                self._log_drop(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    reason_code=reason_code,
                    reason_detail=reason,
                )
                return DiscoveryBridgeResult(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    status=FAILED,
                    reason=reason,
                    reason_code=reason_code,
                )

            conviction_block = self._conviction_entry_block(candidate)
            if conviction_block:
                reason_code, reason = conviction_block
                self.repository.mark_failed(candidate_id=candidate_id, reason=reason)
                self._log_drop(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    reason_code=reason_code,
                    reason_detail=reason,
                )
                return DiscoveryBridgeResult(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    status=FAILED,
                    reason=reason,
                    reason_code=reason_code,
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
            if conviction_active_for_mode(_CONVICTION_CFG, self.config.execution_mode):
                request = replace(
                    request,
                    position_size_pct=float(_CONVICTION_CFG.position_size_pct),
                )
            sizing_block = self._allocation_sizing_block(candidate, request.position_size_pct)
            if sizing_block:
                reason_code, reason = sizing_block
                self.repository.mark_failed(candidate_id=candidate_id, reason=reason)
                self._log_drop(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    reason_code=reason_code,
                    reason_detail=reason,
                )
                return DiscoveryBridgeResult(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    status=FAILED,
                    reason=reason,
                    reason_code=reason_code,
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
                self._record_routed_trade(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    candidate=candidate,
                    order=outcome.order,
                    position_size_pct=request.position_size_pct,
                    stop_loss_pct=request.stop_loss_pct,
                    take_profit_pct=request.take_profit_pct,
                )
                return DiscoveryBridgeResult(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    status=ROUTED,
                    routed_order_id=order_id,
                )

            reason = outcome.live_block_reason or outcome.failure_reason or "order not submitted"
            reason_code = _reason_code_for_order_failure(reason)
            if _is_transient_broker_failure(reason):
                self.repository.mark_retryable(candidate_id=candidate_id, reason=reason)
                self._log_drop(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    reason_code=REASON_CODE_BROKER_TRANSIENT_FAILURE,
                    reason_detail=reason,
                )
                return DiscoveryBridgeResult(
                    candidate_id=candidate_id,
                    symbol=symbol,
                    status=PENDING,
                    reason=reason,
                    reason_code=REASON_CODE_BROKER_TRANSIENT_FAILURE,
                )
            self.repository.mark_failed(candidate_id=candidate_id, reason=reason)
            self._log_drop(
                candidate_id=candidate_id,
                symbol=symbol,
                reason_code=reason_code,
                reason_detail=reason,
            )
            return DiscoveryBridgeResult(
                candidate_id=candidate_id,
                symbol=symbol,
                status=FAILED,
                reason=reason,
                reason_code=reason_code,
            )
        except Exception as exc:
            reason = f"{type(exc).__name__}: {exc}"
            reason_code = (
                REASON_CODE_CANDIDATE_DECODE_FAILED
                if isinstance(exc, (json.JSONDecodeError, ValueError))
                else "bridge_exception"
            )
            self.repository.mark_failed(candidate_id=candidate_id, reason=reason)
            self._log_drop(
                candidate_id=candidate_id,
                symbol=symbol,
                reason_code=reason_code,
                reason_detail=reason,
            )
            return DiscoveryBridgeResult(
                candidate_id=candidate_id,
                symbol=symbol,
                status=FAILED,
                reason=reason,
                reason_code=reason_code,
            )

    def _symbol_cooldown_block(self, symbol: str) -> tuple[str, str] | None:
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
        return REASON_CODE_COOLDOWN_ACTIVE, (
            "bridge blocked: symbol cooldown active "
            f"for {symbol}; prior_candidate_id={recent.get('id')} "
            f"prior_order_id={order_id} prior_timestamp={recent.get('candidate_timestamp')}"
        )

    def _broker_state_block(self, symbol: str) -> tuple[str, str] | None:
        position_getter = getattr(self.broker, "get_position", None)
        if callable(position_getter):
            try:
                position = position_getter(symbol)
            except Exception as exc:
                return (
                    REASON_CODE_POSITION_CHECK_FAILED,
                    f"bridge blocked: broker position check failed: {type(exc).__name__}: {exc}",
                )
            if _position_has_qty(position):
                return (
                    REASON_CODE_OPEN_POSITION_EXISTS,
                    f"bridge blocked: existing open position for {symbol}",
                )

        order_lister = getattr(self.broker, "list_open_orders", None)
        if callable(order_lister):
            try:
                open_orders = order_lister(symbol)
            except Exception as exc:
                return (
                    REASON_CODE_OPEN_ORDER_CHECK_FAILED,
                    f"bridge blocked: broker open-order check failed: {type(exc).__name__}: {exc}",
                )
            if open_orders:
                return (
                    REASON_CODE_OPEN_ORDER_EXISTS,
                    f"bridge blocked: existing open order for {symbol}",
                )

        return None

    def _conviction_entry_block(self, candidate: dict[str, Any]) -> tuple[str, str] | None:
        if not conviction_active_for_mode(_CONVICTION_CFG, self.config.execution_mode):
            return None

        decision = conviction_entry_decision(
            candidate={
                "symbol": candidate.get("symbol"),
                "score": _candidate_conviction_score(candidate),
                "probability_pct": _candidate_probability_pct(candidate),
                "probability_source": candidate.get("probability_source"),
                "probability_percentile_pct": _candidate_probability_percentile_pct(candidate),
                "ml_veto": _candidate_ml_veto(candidate),
                "market_context_ok": _candidate_market_context_ok(candidate),
            },
            account_state={"open_positions": self._open_position_count()},
            last_trade_state={"minutes_since_last_entry": None},
            cfg=_CONVICTION_CFG,
        )
        candidate["conviction_entry_decision"] = decision
        if decision.get("enter"):
            return None

        reason = (
            "bridge blocked: conviction entry gate failed "
            f"reason={decision.get('reason')} checks={decision.get('checks')}"
        )
        return REASON_CODE_CONVICTION_ENTRY_BLOCK, reason

    def _open_position_count(self) -> int:
        position_lister = getattr(self.broker, "list_positions", None)
        if not callable(position_lister):
            return 0
        try:
            positions = position_lister()
        except Exception:
            return 0
        try:
            return len([position for position in positions or [] if _position_has_qty(position)])
        except TypeError:
            return 0

    def _allocation_sizing_block(
        self,
        candidate: dict[str, Any],
        position_size_pct: float,
    ) -> tuple[str, str] | None:
        if self.config.allow_fractional_shares or self.config.min_trade_qty <= 0:
            return None

        price = _candidate_price(candidate)
        allocated_capital = _candidate_allocated_capital(candidate)
        if allocated_capital is None:
            equity = _candidate_account_equity(candidate)
            if equity is not None and position_size_pct > 0:
                allocated_capital = equity * (position_size_pct / 100.0)

        if price is None or allocated_capital is None:
            return None

        estimated_qty = allocated_capital / price
        if estimated_qty >= self.config.min_trade_qty:
            return None

        return REASON_CODE_ALLOCATION_ROUNDS_TO_ZERO, (
            "bridge blocked: allocation rounds below minimum trade quantity "
            f"estimated_qty={estimated_qty:.4f} min_qty={self.config.min_trade_qty:.4f} "
            f"allocated_capital={allocated_capital:.2f} price={price:.4f} "
            f"position_size_pct={position_size_pct:.4f}"
        )

    def _log_drop(
        self,
        *,
        candidate_id: int,
        symbol: str,
        reason_code: str,
        reason_detail: str,
    ) -> None:
        self.logger.info(
            "discovery_execution_bridge_drop candidate_id=%s symbol=%s reason_code=%s reason_detail=%s",
            candidate_id,
            symbol,
            reason_code,
            reason_detail,
        )

    def _record_routed_trade(
        self,
        *,
        candidate_id: int,
        symbol: str,
        candidate: dict[str, Any],
        order: dict[str, Any],
        position_size_pct: float,
        stop_loss_pct: float,
        take_profit_pct: float,
    ) -> None:
        try:
            wrote = self.repository.record_routed_buy_trade(
                candidate=candidate,
                order=order,
                position_size_pct=position_size_pct,
                stop_loss_pct=stop_loss_pct,
                take_profit_pct=take_profit_pct,
            )
        except Exception as exc:
            self.logger.error(
                "discovery_execution_bridge_ledger_write_failed candidate_id=%s symbol=%s error=%s",
                candidate_id,
                symbol,
                f"{type(exc).__name__}: {exc}",
            )
            return
        if not wrote:
            self.logger.info(
                "discovery_execution_bridge_ledger_write_skipped "
                "candidate_id=%s symbol=%s reason=duplicate_or_missing_order_id",
                candidate_id,
                symbol,
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


def _reason_code_for_order_failure(reason: str | None) -> str:
    normalized = str(reason or "").strip().lower()
    if "missing canonical decision trace" in normalized:
        return REASON_CODE_MISSING_CANONICAL_TRACE
    return REASON_CODE_BROKER_REJECTED_ORDER


def _is_transient_broker_failure(reason: str | None) -> bool:
    normalized = str(reason or "").strip().lower()
    return any(
        token in normalized
        for token in (
            "too many requests",
            "rate limit",
            "rate-limit",
            "429",
            "temporarily unavailable",
            "timeout",
            "timed out",
            "connection reset",
            "connection aborted",
            "service unavailable",
            "bad gateway",
            "gateway timeout",
        )
    )


def _candidate_probability_pct(candidate: dict[str, Any]) -> float | None:
    for key in (
        "layered_ml_ensemble_probability_pct",
        "ensemble_probability_pct",
        "probability_pct",
    ):
        value = candidate.get(key)
        try:
            if value not in (None, ""):
                parsed = float(value)
                return parsed * 100.0 if 0 <= parsed <= 1 else parsed
        except (TypeError, ValueError):
            continue
    return None


def _candidate_probability_percentile_pct(candidate: dict[str, Any]) -> float | None:
    for key in ("probability_percentile_pct", "prediction_probability_percentile_pct"):
        value = candidate.get(key)
        try:
            if value not in (None, ""):
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _candidate_conviction_score(candidate: dict[str, Any]) -> float | None:
    for key in ("confluence_score", "conviction_score", "score"):
        value = candidate.get(key)
        try:
            if value not in (None, ""):
                return float(value)
        except (TypeError, ValueError):
            continue
    return None


def _candidate_ml_veto(candidate: dict[str, Any]) -> bool:
    if bool(candidate.get("ml_veto")) or bool(candidate.get("layered_ml_veto")):
        return True
    instruction = str(candidate.get("layered_ml_final_instruction") or "").strip().lower()
    if instruction in {"veto", "block", "hard_block", "paper_avoid"}:
        return True
    reason = str(candidate.get("hard_block_reason") or candidate.get("reason") or "").lower()
    return "layered_ml_veto:veto" in reason


def _candidate_market_context_ok(candidate: dict[str, Any]) -> bool:
    if "market_context_ok" in candidate:
        return bool(candidate.get("market_context_ok"))
    if bool(candidate.get("block_new_buys")):
        return False
    if str(candidate.get("market_bias") or "").strip().lower() in {"avoid", "blocked"}:
        return False
    if candidate.get("avoid_type"):
        return False
    return True


def _float_candidate_value(candidate: dict[str, Any], keys: tuple[str, ...]) -> float | None:
    for key in keys:
        value = candidate.get(key)
        try:
            if value not in (None, ""):
                parsed = float(value)
                if parsed > 0:
                    return parsed
        except (TypeError, ValueError):
            continue
    return None


def _candidate_price(candidate: dict[str, Any]) -> float | None:
    return _float_candidate_value(
        candidate,
        ("current_price", "signal_price", "close", "ask", "mid", "price"),
    )


def _candidate_allocated_capital(candidate: dict[str, Any]) -> float | None:
    return _float_candidate_value(
        candidate,
        (
            "allocated_capital",
            "allocated_notional",
            "risk_amount",
            "target_notional",
            "intended_notional",
        ),
    )


def _candidate_account_equity(candidate: dict[str, Any]) -> float | None:
    return _float_candidate_value(
        candidate,
        ("account_equity", "portfolio_value", "equity", "balance", "buying_power"),
    )
