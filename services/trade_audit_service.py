"""Trade/rejection audit persistence and decision-context attribution."""

from __future__ import annotations

import json
from datetime import datetime
from typing import Any, Callable

from rejection_categories import format_rejection_reason
from repositories import rejections_repo, snapshots_repo, trades_repo


def build_decision_context(
    symbol: str,
    action: str,
    account_state: dict[str, Any] | None = None,
    *,
    market_bias: dict[str, dict[str, Any]],
    trend_table: dict[str, dict[str, Any]],
    log=None,
) -> dict[str, Any]:
    """Snapshot attribution fields for a symbol/action at call time."""
    ctx = {
        "macro_regime": None,
        "risk_multiplier": None,
        "market_bias": None,
        "market_bias_effective": None,
        "market_bias_override_reason": None,
        "fundamental_score": None,
        "risk_level": None,
        "entry_quality": None,
        "trend_direction": None,
        "trend_strength": None,
        "momentum_direction": None,
        "momentum_pct": None,
        "momentum_acceleration_pct": None,
        "momentum_state": None,
        "volume_surge_ratio": None,
        "volume_state": None,
        "extension_from_recent_base_pct": None,
        "rolling_special_labels": None,
        "prior_session_return_pct": None,
        "prior_session_participated": None,
        "tape_label_at_signal": None,
        "tape_bar_age_seconds": None,
        "session_trend_label": None,
        "session_trend_score": None,
        "session_return_pct": None,
        "session_momentum_5m_pct": None,
        "session_momentum_15m_pct": None,
        "session_momentum_30m_pct": None,
        "session_distance_from_vwap_pct": None,
        "session_momentum_reason": None,
        "correlation_cluster": None,
        "cluster_exposure_pct": None,
    }

    try:
        bias_entry = market_bias.get(symbol) or {}
        ctx["market_bias"] = bias_entry.get("bias")
        ctx["fundamental_score"] = bias_entry.get("fundamental_score")
        ctx["risk_level"] = bias_entry.get("risk_level")
        ctx["entry_quality"] = bias_entry.get("entry_quality")

        trend = trend_table.get(symbol) or {}
        ctx["trend_direction"] = trend.get("direction")
        ctx["trend_strength"] = trend.get("strength")

        if account_state:
            macro = account_state.get("macro_risk") or {}
            ctx["macro_regime"] = macro.get("macro_regime")
            ctx["risk_multiplier"] = macro.get("risk_multiplier")
            ctx["market_bias_effective"] = account_state.get("market_bias_effective")
            ctx["market_bias_override_reason"] = account_state.get("market_bias_override_reason")

            momentum = account_state.get("momentum") or {}
            ctx["momentum_direction"] = momentum.get("direction")
            ctx["momentum_pct"] = momentum.get("momentum_pct")
            ctx["momentum_acceleration_pct"] = momentum.get("momentum_acceleration_pct")
            ctx["momentum_state"] = momentum.get("momentum_state")
            ctx["volume_surge_ratio"] = momentum.get("volume_surge_ratio")
            ctx["volume_state"] = momentum.get("volume_state")
            ctx["volume_note"] = momentum.get("volume_note")

            rolling = account_state.get("rolling_momentum") or {}
            ctx["extension_from_recent_base_pct"] = rolling.get("extension_from_recent_base_pct")
            ctx["rolling_special_labels"] = json.dumps(
                rolling.get("special_labels") or [],
                sort_keys=True,
            )

            prior_session = account_state.get("prior_session") or {}
            ctx["prior_session_return_pct"] = prior_session.get("session_return_pct")
            if prior_session.get("participated") is not None:
                ctx["prior_session_participated"] = 1 if prior_session.get("participated") else 0

            tape = account_state.get("tape") or {}
            ctx["tape_label_at_signal"] = tape.get("label")
            ctx["tape_bar_age_seconds"] = tape.get("tape_bar_age_seconds")

            session_momentum = account_state.get("session_momentum") or {}
            ctx["session_trend_label"] = session_momentum.get("trend_label")
            ctx["session_trend_score"] = session_momentum.get("trend_score")
            ctx["session_return_pct"] = session_momentum.get("session_return_pct")
            ctx["session_momentum_5m_pct"] = session_momentum.get("momentum_5m_pct")
            ctx["session_momentum_15m_pct"] = session_momentum.get("momentum_15m_pct")
            ctx["session_momentum_30m_pct"] = session_momentum.get("momentum_30m_pct")
            ctx["session_distance_from_vwap_pct"] = session_momentum.get("distance_from_vwap_pct")
            ctx["session_momentum_reason"] = session_momentum.get("reason")

            corr = account_state.get("correlation_exposure") or []
            if corr:
                primary = max(corr, key=lambda c: c.get("exposure_pct", 0) or 0)
                ctx["correlation_cluster"] = primary.get("cluster")
                ctx["cluster_exposure_pct"] = primary.get("exposure_pct")

    except Exception as exc:
        if log:
            log.warning(f"build_decision_context partial failure for {symbol}: {exc}")

    return ctx


def _trade_columns() -> list[str]:
    return [
        "timestamp",
        "symbol",
        "action",
        "signal_price",
        "approved",
        "rejection_reason",
        "confidence",
        "position_size_pct",
        "stop_loss_pct",
        "take_profit_pct",
        "order_id",
        "order_status",
        "qty",
        "fill_price",
        "macro_regime",
        "risk_multiplier",
        "market_bias",
        "market_bias_effective",
        "market_bias_override_reason",
        "fundamental_score",
        "risk_level",
        "entry_quality",
        "trend_direction",
        "trend_strength",
        "momentum_direction",
        "momentum_pct",
        "session_trend_label",
        "session_trend_score",
        "session_return_pct",
        "session_momentum_5m_pct",
        "session_momentum_15m_pct",
        "session_momentum_30m_pct",
        "session_distance_from_vwap_pct",
        "session_momentum_reason",
        "prediction_score",
        "prediction_decision",
        "prediction_reason",
        "correlation_cluster",
        "cluster_exposure_pct",
        "setup_label",
        "setup_policy_action",
        "setup_policy_reason",
        "setup_confidence_adjustment",
        "setup_size_multiplier",
        "setup_unknown_reason",
        "ml_prediction_score",
        "ml_prediction_bucket",
        "buy_opportunity_score",
        "buy_opportunity_recommendation",
        "buy_opportunity_reason",
        "trader_brain_score",
        "trader_brain_setup_type",
        "trader_brain_approved",
        "trader_brain_reason",
        "trader_brain_positive_factors",
        "trader_brain_risk_factors",
        "session_momentum_severity",
        "effective_size_cap_pct",
        "dominant_limiter",
    ]


def _rejection_columns() -> list[str]:
    columns = _trade_columns()
    remove = {
        "confidence",
        "position_size_pct",
        "stop_loss_pct",
        "take_profit_pct",
        "order_id",
        "order_status",
        "qty",
        "fill_price",
        "buy_opportunity_score",
        "buy_opportunity_recommendation",
        "buy_opportunity_reason",
    }
    return [column for column in columns if column not in remove]


def _shared_values(
    *,
    timestamp: str,
    symbol: str,
    action: str,
    price,
    approved: bool,
    rejection_reason,
    decision: dict[str, Any],
    order: dict[str, Any],
    account_state: dict[str, Any] | None,
    context: dict[str, Any],
    ml_prediction_bucket: Callable[[Any], str],
) -> dict[str, Any]:
    account_state = account_state or {}
    setup_obs = account_state.get("setup_observation") or {}
    prediction_gate = account_state.get("prediction_gate") or {}
    strategy_observation = account_state.get("strategy_observation") or {}
    trader_brain = strategy_observation.get("trader_brain") or {}

    return {
        "timestamp": timestamp,
        "symbol": symbol,
        "action": action,
        "signal_price": price,
        "approved": 1 if approved else 0,
        "rejection_reason": rejection_reason,
        "confidence": decision.get("confidence"),
        "position_size_pct": decision.get("position_size_pct"),
        "stop_loss_pct": decision.get("stop_loss_pct"),
        "take_profit_pct": decision.get("take_profit_pct"),
        "order_id": order.get("order_id"),
        "order_status": order.get("status"),
        "qty": order.get("qty"),
        "fill_price": order.get("fill_price"),
        "macro_regime": context["macro_regime"],
        "risk_multiplier": context["risk_multiplier"],
        "market_bias": context["market_bias"],
        "market_bias_effective": context["market_bias_effective"],
        "market_bias_override_reason": context["market_bias_override_reason"],
        "fundamental_score": context["fundamental_score"],
        "risk_level": context["risk_level"],
        "entry_quality": context["entry_quality"],
        "trend_direction": context["trend_direction"],
        "trend_strength": context["trend_strength"],
        "momentum_direction": context["momentum_direction"],
        "momentum_pct": context["momentum_pct"],
        "session_trend_label": context["session_trend_label"],
        "session_trend_score": context["session_trend_score"],
        "session_return_pct": context["session_return_pct"],
        "session_momentum_5m_pct": context["session_momentum_5m_pct"],
        "session_momentum_15m_pct": context["session_momentum_15m_pct"],
        "session_momentum_30m_pct": context["session_momentum_30m_pct"],
        "session_distance_from_vwap_pct": context["session_distance_from_vwap_pct"],
        "session_momentum_reason": context["session_momentum_reason"],
        "prediction_score": prediction_gate.get("prediction_score"),
        "prediction_decision": prediction_gate.get("prediction_decision"),
        "prediction_reason": prediction_gate.get("prediction_reason"),
        "correlation_cluster": context["correlation_cluster"],
        "cluster_exposure_pct": context["cluster_exposure_pct"],
        "setup_label": setup_obs.get("setup_label"),
        "setup_policy_action": setup_obs.get("setup_policy_action"),
        "setup_policy_reason": setup_obs.get("setup_policy_reason"),
        "setup_confidence_adjustment": setup_obs.get("setup_confidence_adjustment"),
        "setup_size_multiplier": setup_obs.get("setup_size_multiplier"),
        "setup_unknown_reason": setup_obs.get("setup_unknown_reason"),
        "ml_prediction_score": prediction_gate.get("ml_prediction_score"),
        "ml_prediction_bucket": ml_prediction_bucket(prediction_gate.get("ml_prediction_score")),
        "buy_opportunity_score": account_state.get("buy_opportunity", {}).get("buy_opportunity_score"),
        "buy_opportunity_recommendation": account_state.get("buy_opportunity", {}).get("buy_opportunity_recommendation"),
        "buy_opportunity_reason": account_state.get("buy_opportunity", {}).get("buy_opportunity_reason"),
        "trader_brain_score": trader_brain.get("score"),
        "trader_brain_setup_type": trader_brain.get("setup_type"),
        "trader_brain_approved": (
            1 if trader_brain.get("approved_by_scorer") is True
            else 0 if trader_brain.get("approved_by_scorer") is False
            else None
        ),
        "trader_brain_reason": trader_brain.get("reason"),
        "trader_brain_positive_factors": json.dumps(
            trader_brain.get("positive_factors") or [],
            sort_keys=True,
        ),
        "trader_brain_risk_factors": json.dumps(
            trader_brain.get("risk_factors") or [],
            sort_keys=True,
        ),
        "session_momentum_severity": account_state.get("conviction_stack", {}).get("session_severity"),
        "effective_size_cap_pct": account_state.get("conviction_stack", {}).get("effective_cap_pct"),
        "dominant_limiter": account_state.get("dominant_limiter"),
    }


def log_trade(
    signal: dict[str, Any],
    decision: dict[str, Any],
    order: dict[str, Any] | None,
    *,
    account_state: dict[str, Any] | None,
    market_bias: dict[str, dict[str, Any]],
    trend_table: dict[str, dict[str, Any]],
    ml_prediction_bucket: Callable[[Any], str],
    log,
) -> None:
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    with open("signals.log", "a") as f:
        line = (
            f"{timestamp} | SIGNAL: {json.dumps(signal)} | "
            f"DECISION: {json.dumps(decision)} | ORDER: {json.dumps(order)}"
        )
        f.write(line + "\n")

    try:
        approved = decision.get("approved", False)
        order = order or {}
        context = build_decision_context(
            signal.get("symbol"),
            signal.get("action"),
            account_state,
            market_bias=market_bias,
            trend_table=trend_table,
            log=log,
        )
        values_by_column = _shared_values(
            timestamp=timestamp,
            symbol=signal.get("symbol"),
            action=signal.get("action"),
            price=signal.get("price"),
            approved=approved,
            rejection_reason=None if approved else decision.get("reason"),
            decision=decision,
            order=order,
            account_state=account_state,
            context=context,
            ml_prediction_bucket=ml_prediction_bucket,
        )
        columns = _trade_columns()
        trade_id = trades_repo.insert_trade_row(
            columns,
            [values_by_column[column] for column in columns],
        )

        try:
            snapshots_repo.record_snapshot(
                trade_id=trade_id,
                timestamp=timestamp,
                source="trade_audit_service.log_trade",
                symbol=signal.get("symbol"),
                action=signal.get("action"),
                signal_price=signal.get("price"),
                decision=decision,
                order=order,
                context=context,
                account_state=account_state,
                raw_signal=signal,
                rejection_reason=None if approved else decision.get("reason"),
            )
        except Exception as snapshot_error:
            log.warning(f"decision snapshot write failed for {signal.get('symbol')}: {snapshot_error}")

    except Exception as exc:
        log.error(f"DB write failed for {signal.get('symbol')}: {exc}")


def log_rejection(
    symbol: str,
    action: str,
    category: str,
    reason: str,
    *,
    price=None,
    account_state: dict[str, Any] | None,
    market_bias: dict[str, dict[str, Any]],
    trend_table: dict[str, dict[str, Any]],
    ml_prediction_bucket: Callable[[Any], str],
    log,
) -> None:
    """Persist a pre-Claude rejection to trades.db so reports can count it."""
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    full_reason = format_rejection_reason(category, reason)
    context = build_decision_context(
        symbol,
        action,
        account_state,
        market_bias=market_bias,
        trend_table=trend_table,
        log=log,
    )
    decision = {"approved": False, "reason": full_reason}
    values_by_column = _shared_values(
        timestamp=timestamp,
        symbol=symbol,
        action=action,
        price=price,
        approved=False,
        rejection_reason=full_reason,
        decision=decision,
        order={},
        account_state=account_state,
        context=context,
        ml_prediction_bucket=ml_prediction_bucket,
    )
    columns = _rejection_columns()

    try:
        trade_id = rejections_repo.insert_rejection_row(
            columns,
            [values_by_column[column] for column in columns],
        )
        try:
            snapshots_repo.record_snapshot(
                trade_id=trade_id,
                timestamp=timestamp,
                source="trade_audit_service.log_rejection",
                symbol=symbol,
                action=action,
                signal_price=price,
                decision=decision,
                order={},
                context=context,
                account_state=account_state,
                raw_signal={"symbol": symbol, "action": action, "price": price},
                rejection_reason=full_reason,
            )
        except Exception as snapshot_error:
            log.warning(f"decision snapshot write failed for {symbol}: {snapshot_error}")
    except Exception as exc:
        log.error(f"log_rejection DB write failed for {symbol}: {exc}")


def record_webhook_status(
    *,
    dedupe_key: str | None,
    status: str,
    mark_webhook_event_status: Callable[..., None],
    order_id=None,
    client_order_id=None,
    failure_reason=None,
    log=None,
) -> None:
    """Persist webhook processing status through an injected repository/service."""
    if not dedupe_key:
        return
    try:
        mark_webhook_event_status(
            dedupe_key,
            status,
            order_id=order_id,
            client_order_id=client_order_id,
            failure_reason=failure_reason,
        )
    except Exception as exc:
        if log:
            log.warning(f"webhook status write failed for {dedupe_key}: {exc}")


def record_rejection(
    *,
    symbol: str,
    action: str,
    category: str,
    reason: str,
    price=None,
    account_state: dict[str, Any] | None,
    dedupe_key: str | None = None,
    mark_webhook_event_status: Callable[..., None] | None = None,
    market_bias: dict[str, dict[str, Any]],
    trend_table: dict[str, dict[str, Any]],
    ml_prediction_bucket: Callable[[Any], str],
    log,
) -> None:
    """Record a rejected signal and optionally mark the webhook as rejected."""
    log_rejection(
        symbol,
        action,
        category,
        reason,
        price=price,
        account_state=account_state,
        market_bias=market_bias,
        trend_table=trend_table,
        ml_prediction_bucket=ml_prediction_bucket,
        log=log,
    )
    if mark_webhook_event_status:
        record_webhook_status(
            dedupe_key=dedupe_key,
            status="rejected",
            mark_webhook_event_status=mark_webhook_event_status,
            failure_reason=f"{category}: {reason}",
            log=log,
        )


def record_execution(
    *,
    signal: dict[str, Any],
    decision: dict[str, Any],
    order: dict[str, Any] | None,
    account_state: dict[str, Any] | None,
    dedupe_key: str | None = None,
    webhook_status: str = "processed",
    mark_webhook_event_status: Callable[..., None] | None = None,
    market_bias: dict[str, dict[str, Any]],
    trend_table: dict[str, dict[str, Any]],
    ml_prediction_bucket: Callable[[Any], str],
    log,
) -> None:
    """Record the final approved/rejected trade row and webhook status."""
    log_trade(
        signal,
        decision,
        order,
        account_state=account_state,
        market_bias=market_bias,
        trend_table=trend_table,
        ml_prediction_bucket=ml_prediction_bucket,
        log=log,
    )
    if mark_webhook_event_status:
        record_webhook_status(
            dedupe_key=dedupe_key,
            status=webhook_status,
            mark_webhook_event_status=mark_webhook_event_status,
            order_id=(order or {}).get("order_id"),
            client_order_id=(order or {}).get("client_order_id"),
            failure_reason=None if webhook_status == "processed" else decision.get("reason"),
            log=log,
        )


class TradeAuditService:
    """Object wrapper for audit persistence.

    The module-level functions remain for compatibility while the signal
    pipeline migrates away from app-level shims. New code should depend on this
    class so tests can patch a stable service boundary.
    """

    def __init__(
        self,
        *,
        market_bias: dict[str, dict[str, Any]],
        trend_table: dict[str, dict[str, Any]],
        ml_prediction_bucket: Callable[[Any], str],
        log,
        mark_webhook_event_status: Callable[..., None] | None = None,
    ):
        self.market_bias = market_bias
        self.trend_table = trend_table
        self.ml_prediction_bucket = ml_prediction_bucket
        self.log = log
        self.mark_webhook_event_status = mark_webhook_event_status

    def build_decision_context(
        self,
        symbol: str,
        action: str,
        account_state: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        return build_decision_context(
            symbol,
            action,
            account_state,
            market_bias=self.market_bias,
            trend_table=self.trend_table,
            log=self.log,
        )

    def record_rejection(
        self,
        *,
        symbol: str,
        action: str,
        category: str,
        reason: str,
        price=None,
        account_state: dict[str, Any] | None,
        dedupe_key: str | None = None,
    ) -> None:
        return record_rejection(
            symbol=symbol,
            action=action,
            category=category,
            reason=reason,
            price=price,
            account_state=account_state,
            dedupe_key=dedupe_key,
            mark_webhook_event_status=self.mark_webhook_event_status,
            market_bias=self.market_bias,
            trend_table=self.trend_table,
            ml_prediction_bucket=self.ml_prediction_bucket,
            log=self.log,
        )

    def record_execution(
        self,
        *,
        signal: dict[str, Any],
        decision: dict[str, Any],
        order: dict[str, Any] | None,
        account_state: dict[str, Any] | None,
        dedupe_key: str | None = None,
        webhook_status: str = "processed",
    ) -> None:
        return record_execution(
            signal=signal,
            decision=decision,
            order=order,
            account_state=account_state,
            dedupe_key=dedupe_key,
            webhook_status=webhook_status,
            mark_webhook_event_status=self.mark_webhook_event_status,
            market_bias=self.market_bias,
            trend_table=self.trend_table,
            ml_prediction_bucket=self.ml_prediction_bucket,
            log=self.log,
        )

    def record_webhook_status(
        self,
        *,
        dedupe_key: str | None,
        status: str,
        order_id=None,
        client_order_id=None,
        failure_reason=None,
    ) -> None:
        if not self.mark_webhook_event_status:
            return None
        return record_webhook_status(
            dedupe_key=dedupe_key,
            status=status,
            mark_webhook_event_status=self.mark_webhook_event_status,
            order_id=order_id,
            client_order_id=client_order_id,
            failure_reason=failure_reason,
            log=self.log,
        )
