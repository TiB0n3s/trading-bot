"""Service-owned live signal orchestration."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
import os
from typing import Any, Callable

from rejection_categories import format_rejection_reason
from services import signal_stage_guards
from services.approval_service import (
    ApprovalDecision,
    RejectionAdapter,
    deterministic_rejection,
    execution_rejection_decision,
    run_claude_and_confidence,
    run_entry_sanity_gates,
    run_final_approval_gates,
    run_intra_session_tape_degradation_gate,
    run_macro_position_gate,
    run_prediction_session_tape_gates,
    run_trend_confirmation_gate,
    setup_policy_rejection,
)
from services.execution_service import execute_approved_order
from services.signal_models import ExecutionResult, PipelineResult, SignalContext, SignalRuntimeState


def build_runtime_state(
    signal_context: SignalContext,
    *,
    load_market_context: Callable[[], Any],
    get_account_state: Callable[[], dict[str, Any]],
) -> SignalRuntimeState:
    load_market_context()
    return SignalRuntimeState(
        raw_signal=signal_context.raw_signal,
        symbol=signal_context.symbol,
        action=signal_context.action,
        received_at=datetime.now(timezone.utc),
        account_state=get_account_state(),
    )


def build_context_runtime(
    runtime_state: SignalRuntimeState,
    *,
    build_signal_context: Callable[..., Any],
    context_deps: Any,
) -> Any:
    return build_signal_context(runtime_state, context_deps)


@dataclass(frozen=True)
class StageResult:
    rejected: bool = False
    response: object | None = None


@dataclass(frozen=True)
class ClaudeStageResult:
    rejected: bool = False
    decision: dict | None = None
    response: object | None = None


@dataclass(frozen=True)
class ApprovalGateResult:
    rejected: bool = False
    claude_account_state: dict | None = None
    response: object | None = None


@dataclass(frozen=True)
class LiveSignalProcessorDeps:
    log: Any
    log_rejection: Callable[..., Any]
    record_webhook_status: Callable[..., Any]
    parse_stale_signal: Callable[[dict[str, Any]], tuple[bool, Any, str]]
    is_cash_safe_mode: Callable[[], bool]
    cash_safe_symbols: set[str]
    cash_safe_max_open_positions: int
    cash_safe_max_new_buys_per_symbol_per_day: int
    cash_safe_buys_today: Callable[[str], int]
    symbol_override_block: Callable[[str, str], str | None]
    enforce_setup_policy_blocks: bool
    apply_size_cap: Callable[..., Any]
    trend_table: dict[str, Any]
    env_float: Callable[[str, float], float]
    is_unrecognized_setup_label: Callable[[dict[str, Any]], bool]
    count_second_look_blocks_today: Callable[[str], int]
    apply_market_bias_context: Callable[..., Any]
    update_trend_history: Callable[[str, str], Any]
    sell_continuation_delay_reason: Callable[..., str | None]
    hydrate_pre_macro_context: Callable[..., dict[str, Any]]
    hydrate_session_context: Callable[..., Any]
    hydrate_buy_momentum_context: Callable[..., Any]
    hydrate_strategy_context: Callable[..., Any]
    macro_position_count_floor: float
    get_latest_session_momentum: Callable[[str], dict[str, Any] | None]
    session_momentum_is_fresh: Callable[[dict[str, Any]], bool]
    weakest_position_context: Callable[[dict[str, Any]], dict[str, Any] | None]
    evaluate_buy_opportunity: Callable[..., dict[str, Any]]
    required_buy_confirmations: Callable[[str, dict[str, Any] | None], dict[str, Any]]
    try_portfolio_rotation: Callable[..., tuple[bool, str, dict[str, Any]]]
    get_account_state: Callable[[], dict[str, Any]]
    sleep: Callable[[float], None]
    required_sell_confirmations: Callable[[str, dict[str, Any] | None], dict[str, Any]]
    is_fast_lane_buy_flip: Callable[..., bool]
    is_fast_lane_sell_flip: Callable[..., bool]
    market_open_minutes: int
    open_momentum_fast_lane_enabled: bool
    iex_thin_symbols: set[str]
    adaptive_buy_confirmation_enabled: bool
    execution_mode: str
    evaluate_signal_quality_gate: Callable[..., dict[str, Any]]
    get_cached_prediction: Callable[[str], dict[str, Any] | None]
    ml_prediction_bucket: Callable[[Any], str]
    live_bias_override: Callable[..., dict[str, Any]]
    evaluate_session_momentum_gate: Callable[..., dict[str, Any]]
    prediction_soft_avoid_min_sample_size: int
    enforce_prediction_blocks: bool
    enforce_prediction_watch_in_cash: bool
    prediction_gate_mode: str
    ml_authority_config: dict[str, Any]
    is_cash_mode: Callable[[], bool]
    enforce_session_momentum_gate: bool
    is_degraded_setup: Callable[[dict[str, Any]], bool]
    intra_session_tape_degradation_enabled: bool
    intra_session_tape_degradation_start_hour_et: int
    intra_session_tape_degradation_min_setup_score: float
    et_timezone: Any
    score_buy_opportunity: Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]]
    memory_for_signal: Callable[[str, dict[str, Any]], dict[str, Any]]
    build_intelligence_context: Callable[..., dict[str, Any]]
    evaluate_decision_policy: Callable[..., dict[str, Any]]
    public_decision_policy_config: Callable[[], dict[str, Any]]
    decision_policy_live_authority_enabled: Callable[[], bool]
    decision_policy_live_block_enabled: bool
    decision_policy_live_size_down_enabled: bool
    build_conviction_stack: Callable[..., Any]
    compute_dominant_limiter: Callable[..., Any]
    log_event: Callable[..., Any]
    weekly_symbol_performance: Callable[[str], dict[str, Any]]
    medium_confidence_override: Callable[..., tuple[bool, str]]
    evaluate_signal: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]]
    tape_exception_enabled: bool
    market_bias: dict[str, Any]
    apply_final_sizing: Callable[..., Any]
    apply_buy_opportunity_sizing: Callable[..., Any]
    execute_order: Callable[..., Any]
    pre_order_safety_check: Callable[..., tuple[bool, str]]
    one_bar_confirmation_hold: Callable[..., tuple[bool, str]]
    make_client_order_id: Callable[[str, str, dict[str, Any]], str]
    place_order: Callable[..., dict[str, Any] | None]
    log_trade: Callable[..., Any]
    write_cooldown: Callable[[str, str, Any], Any]
    write_recent_sell: Callable[[str, Any, Any], Any]
    last_order: dict
    last_sell: dict


class LiveSignalProcessor:
    def __init__(self, deps: LiveSignalProcessorDeps):
        self.deps = deps

    def process(
        self,
        context: SignalContext,
        runtime_state: SignalRuntimeState,
        context_runtime: Any,
        preflight_result: Any | None = None,
    ) -> PipelineResult:
        data = context.raw_signal
        dedupe_key = context.dedupe_key
        symbol = runtime_state.symbol
        action = runtime_state.action
        price = context.price
        self.deps.log.info(f"Processing {action.upper()} signal for {symbol} at {price}")

        account_state = runtime_state.account_state
        setup_obs = context_runtime.built.setup.data
        rejection_adapter = self._rejection_adapter(
            symbol=symbol,
            action=action,
            price=price,
            account_state=account_state,
            dedupe_key=dedupe_key,
        )

        stale_result = self.check_stale_signal(
            data=data,
            symbol=symbol,
            action=action,
            price=price,
            account_state=account_state,
            dedupe_key=dedupe_key,
        )
        if stale_result.rejected:
            return self._result(context)

        setup_stage_result = self.apply_setup_stage(
            symbol=symbol,
            action=action,
            price=price,
            account_state=account_state,
            dedupe_key=dedupe_key,
            setup_obs=setup_obs,
        )
        if setup_stage_result.rejected:
            return self._result(context)

        cash_safe_result = self.check_cash_safe_gates(
            symbol=symbol,
            action=action,
            price=price,
            account_state=account_state,
            dedupe_key=dedupe_key,
        )
        if cash_safe_result.rejected:
            return self._result(context)

        symbol_override_result = self.check_symbol_override(
            symbol=symbol,
            action=action,
            price=price,
            account_state=account_state,
            dedupe_key=dedupe_key,
        )
        if symbol_override_result.rejected:
            return self._result(context)

        self.deps.update_trend_history(symbol, action)

        current_et = (
            preflight_result.metadata.get("current_et")
            if preflight_result is not None
            else None
        )
        existing_position = (
            preflight_result.metadata.get("existing_position")
            if preflight_result is not None
            else None
        )

        sell_discipline_result = self.check_sell_discipline(
            symbol=symbol,
            action=action,
            price=price,
            account_state=account_state,
            dedupe_key=dedupe_key,
            existing_position=existing_position,
        )
        if sell_discipline_result.rejected:
            return self._result(context)

        macro_risk = self.deps.hydrate_pre_macro_context(
            symbol=symbol,
            action=action,
            account_state=account_state,
            context_runtime=context_runtime,
        )

        macro_gate_result = self.run_macro_position_gate(
            symbol=symbol,
            action=action,
            price=price,
            account_state=account_state,
            context_runtime=context_runtime,
            current_et=current_et,
            macro_risk=macro_risk,
            rejection_adapter=rejection_adapter,
        )
        if macro_gate_result.rejected:
            return self._result(context)

        trend_gate_result = self.run_trend_confirmation_gate(
            symbol=symbol,
            action=action,
            price=price,
            account_state=account_state,
            context_runtime=context_runtime,
            current_et=current_et,
            rejection_adapter=rejection_adapter,
        )
        if trend_gate_result.rejected:
            return self._result(context)

        bias_entry = self.deps.market_bias.get(symbol) or {}
        entry_sanity_result = self.run_entry_sanity_gates(
            symbol=symbol,
            action=action,
            price=price,
            account_state=account_state,
            bias_entry=bias_entry,
            existing_position=existing_position,
            rejection_adapter=rejection_adapter,
        )
        if entry_sanity_result.rejected:
            return self._result(context)

        self.deps.hydrate_session_context(context_runtime=context_runtime)

        if action == "sell" and existing_position:
            try:
                avg_entry = float(existing_position.get("avg_entry") or 0)
                current_price = float(existing_position.get("current_price") or price or 0)
                qty = float(existing_position.get("qty") or 0)
                if avg_entry > 0 and current_price > 0 and qty > 0:
                    unrealized_pct = (current_price - avg_entry) / avg_entry * 100.0
                    continuation_reason = self.deps.sell_continuation_delay_reason(
                        account_state,
                        self.deps.trend_table.get(symbol) or {},
                        unrealized_pct,
                    )
                    if continuation_reason:
                        if rejection_adapter.reject_current_signal(
                            "sell_continuation_check",
                            continuation_reason,
                        ):
                            return self._result(context)
            except Exception as exc:
                self.deps.log.warning(
                    f"Sell continuation check failed for {symbol}; fail-open for SELL safety: {exc}"
                )

        self.deps.hydrate_buy_momentum_context(
            symbol=symbol,
            action=action,
            account_state=account_state,
            context_runtime=context_runtime,
        )
        prediction_gate_result = self.run_prediction_bias_session_gate(
            symbol=symbol,
            action=action,
            price=price,
            account_state=account_state,
            context_runtime=context_runtime,
            rejection_adapter=rejection_adapter,
        )
        if prediction_gate_result.rejected:
            return self._result(context)

        tape_degradation_result = self.run_intra_session_tape_degradation_gate(
            symbol=symbol,
            action=action,
            price=price,
            account_state=account_state,
            rejection_adapter=rejection_adapter,
        )
        if tape_degradation_result.rejected:
            return self._result(context)

        self.deps.hydrate_strategy_context(
            symbol=symbol,
            action=action,
            account_state=account_state,
            context_runtime=context_runtime,
        )

        final_gate_result = self.run_final_approval_gates(
            data=data,
            symbol=symbol,
            action=action,
            price=price,
            account_state=account_state,
            context_runtime=context_runtime,
            rejection_adapter=rejection_adapter,
        )
        if final_gate_result.rejected:
            return self._result(context)
        claude_account_state = final_gate_result.claude_account_state or dict(account_state)

        claude_result = self.run_claude_and_confidence(
            data=data,
            symbol=symbol,
            action=action,
            price=price,
            account_state=account_state,
            claude_account_state=claude_account_state,
            rejection_adapter=rejection_adapter,
        )
        if claude_result.rejected:
            return self._result(context)
        decision = dict(claude_result.decision or {})
        order_path_result = self.run_approved_order_path(
            data=data,
            symbol=symbol,
            action=action,
            price=price,
            account_state=account_state,
            dedupe_key=dedupe_key,
            current_et=current_et,
            decision=decision,
            rejection_adapter=rejection_adapter,
        )
        if order_path_result.rejected:
            return self._result(context)

        return self._result(context)

    def _result(self, context: SignalContext) -> PipelineResult:
        return PipelineResult(
            handled=True,
            context=context,
            execution=ExecutionResult(
                submitted=False,
                status="handled_by_live_signal_processor",
            ),
        )

    def _reject_current_signal(
        self,
        *,
        symbol: str,
        action: str,
        price: Any,
        account_state: dict[str, Any],
        dedupe_key: str | None,
        category: str,
        reason: str,
        level: str = "warning",
    ) -> StageResult:
        if level == "error":
            self.deps.log.error(f"{category} blocked {symbol} {action.upper()}: {reason}")
        elif level == "info":
            self.deps.log.info(f"{category} blocked {symbol} {action.upper()}: {reason}")
        else:
            self.deps.log.warning(f"{category} blocked {symbol} {action.upper()}: {reason}")

        self.deps.log_rejection(
            symbol,
            action,
            category,
            reason,
            price=price,
            account_state=account_state,
        )

        if dedupe_key:
            self.deps.record_webhook_status(
                dedupe_key=dedupe_key,
                status="rejected",
                failure_reason=format_rejection_reason(category, reason),
            )

        return StageResult(rejected=True)

    def _reject_approval_decision(
        self,
        *,
        symbol: str,
        action: str,
        price: Any,
        account_state: dict[str, Any],
        dedupe_key: str | None,
        approval: ApprovalDecision,
        level: str = "warning",
    ) -> StageResult:
        return self._reject_current_signal(
            symbol=symbol,
            action=action,
            price=price,
            account_state=account_state,
            dedupe_key=dedupe_key,
            category=approval.category or "approval_rejection",
            reason=approval.reason,
            level=level,
        )

    def _rejection_adapter(
        self,
        *,
        symbol: str,
        action: str,
        price: Any,
        account_state: dict[str, Any],
        dedupe_key: str | None,
    ) -> RejectionAdapter:
        return RejectionAdapter(
            reject_current_signal=(
                lambda category, reason, level="warning": self._reject_current_signal(
                    symbol=symbol,
                    action=action,
                    price=price,
                    account_state=account_state,
                    dedupe_key=dedupe_key,
                    category=category,
                    reason=reason,
                    level=level,
                ).rejected
            ),
            reject_approval_decision=(
                lambda approval, level="warning": self._reject_approval_decision(
                    symbol=symbol,
                    action=action,
                    price=price,
                    account_state=account_state,
                    dedupe_key=dedupe_key,
                    approval=approval,
                    level=level,
                ).rejected
            ),
        )

    def check_stale_signal(self, *, data, symbol, action, price, account_state, dedupe_key):
        decision = signal_stage_guards.check_stale_signal(
            raw_signal=data,
            parse_stale_signal=self.deps.parse_stale_signal,
        )
        account_state.update(decision.account_state_updates)
        if decision.rejected and decision.approval:
            return self._reject_approval_decision(
                symbol=symbol,
                action=action,
                price=price,
                account_state=account_state,
                dedupe_key=dedupe_key,
                approval=decision.approval,
            )

        return StageResult()

    def check_cash_safe_gates(self, *, symbol, action, price, account_state, dedupe_key):
        decision = signal_stage_guards.check_cash_safe_gates(
            symbol=symbol,
            action=action,
            account_state=account_state,
            cash_safe_mode=self.deps.is_cash_safe_mode(),
            cash_safe_symbols=self.deps.cash_safe_symbols,
            max_open_positions=self.deps.cash_safe_max_open_positions,
            max_new_buys_per_symbol_per_day=(
                self.deps.cash_safe_max_new_buys_per_symbol_per_day
            ),
            cash_safe_buys_today=self.deps.cash_safe_buys_today,
            log=self.deps.log,
        )
        if decision.rejected and decision.approval:
            return self._reject_approval_decision(
                symbol=symbol,
                action=action,
                price=price,
                account_state=account_state,
                dedupe_key=dedupe_key,
                approval=decision.approval,
            )

        return StageResult()

    def check_symbol_override(self, *, symbol, action, price, account_state, dedupe_key):
        decision = signal_stage_guards.apply_symbol_overrides(
            symbol=symbol,
            action=action,
            symbol_override_block=self.deps.symbol_override_block,
        )
        if decision.rejected and decision.approval:
            return self._reject_approval_decision(
                symbol=symbol,
                action=action,
                price=price,
                account_state=account_state,
                dedupe_key=dedupe_key,
                approval=decision.approval,
            )

        return StageResult()

    def apply_setup_stage(self, *, symbol, action, price, account_state, dedupe_key, setup_obs):
        if (
            action == "buy"
            and self.deps.enforce_setup_policy_blocks
            and setup_obs.get("setup_policy_action") == "block"
        ):
            setup_label = setup_obs.get("setup_label") or ""
            reason = setup_obs.get("setup_policy_reason") or "setup_policy:block"

            session_label = account_state.get("session_trend_label")
            session_score = float(account_state.get("session_trend_score") or 0)
            session_m5 = float(account_state.get("session_momentum_5m_pct") or 0)
            session_m15 = float(account_state.get("session_momentum_15m_pct") or 0)
            session_m30 = float(account_state.get("session_momentum_30m_pct") or 0)
            session_vwap = float(account_state.get("session_distance_from_vwap_pct") or 0)

            stretched_but_confirmed = (
                setup_label == "avoid_stretched_above_vwap_strength"
                and session_label == "strong_uptrend"
                and session_score >= 6
                and session_m5 > 0
                and session_m15 > 0
                and session_m30 > 0
                and session_vwap <= 1.75
            )

            if stretched_but_confirmed:
                account_state["setup_policy_override"] = {
                    "from": "block",
                    "to": "allow_reduced_size",
                    "reason": (
                        "stretched setup allowed reduced-size due to confirmed session strength: "
                        f"label={session_label} score={session_score} "
                        f"5m={session_m5:.3f}% 15m={session_m15:.3f}% "
                        f"30m={session_m30:.3f}% vwap={session_vwap:.3f}%"
                    ),
                }
                self.deps.apply_size_cap(
                    account_state,
                    cap_pct=0.75,
                    state_key="setup_policy_size_cap",
                    payload={"cap_pct": 0.75, "source": "setup_policy_override"},
                )

                self.deps.log.warning(
                    f"Setup policy override for {symbol}: "
                    f"{account_state['setup_policy_override']['reason']}"
                )
            else:
                return self._reject_approval_decision(
                    symbol=symbol,
                    action=action,
                    price=price,
                    account_state=account_state,
                    dedupe_key=dedupe_key,
                    approval=setup_policy_rejection(
                        reason,
                        metadata={"setup_label": setup_label},
                    ),
                )

        if action == "buy" and setup_obs.get("setup_policy_action") == "error":
            deg_trend = self.deps.trend_table.get(symbol) or {}
            deg_trend_dir = deg_trend.get("direction")
            deg_trend_str = deg_trend.get("strength")
            has_strong_context = (
                deg_trend_dir == "bullish"
                and deg_trend_str in ("confirmed", "developing")
            )
            deg_cap = 1.0 if has_strong_context else 0.75
            self.deps.apply_size_cap(
                account_state,
                cap_pct=deg_cap,
                state_key="setup_degraded",
                payload={
                    "reason": setup_obs.get("setup_unknown_reason") or "build_snapshot_failed",
                    "size_cap_pct": deg_cap,
                    "has_strong_context": has_strong_context,
                    "trend_direction": deg_trend_dir,
                    "trend_strength": deg_trend_str,
                },
            )
            self.deps.log.warning(
                f"Degraded setup (error) for {symbol}: size capped at {deg_cap}%, "
                f"strong_context={has_strong_context} "
                f"({deg_trend_dir}/{deg_trend_str}), "
                f"reason={setup_obs.get('setup_unknown_reason')}"
            )

        if action == "buy" and self.deps.is_unrecognized_setup_label(setup_obs):
            unrecog_cap = self.deps.env_float("UNRECOGNIZED_LABEL_SIZE_CAP_PCT", 0.85)
            self.deps.apply_size_cap(
                account_state,
                cap_pct=unrecog_cap,
                state_key="unrecognized_label_cap",
                payload={
                    "setup_unknown_reason": setup_obs.get("setup_unknown_reason"),
                    "cap_pct": unrecog_cap,
                },
            )
            self.deps.log.warning(
                f"Unrecognized setup label size cap for {symbol}: "
                f"{setup_obs.get('setup_unknown_reason')} → {unrecog_cap}%"
            )

        if action == "buy":
            setup_label = setup_obs.get("setup_label") or ""

            session_return_pct = float(account_state.get("session_return_pct") or 0)
            session_vwap_dist_pct = float(account_state.get("session_distance_from_vwap_pct") or 0)
            session_m15_pct = float(account_state.get("session_momentum_15m_pct") or 0)
            session_m30_pct = float(account_state.get("session_momentum_30m_pct") or 0)

            if setup_label == "unclassified_transition" and session_vwap_dist_pct >= float(
                os.getenv("UNCLASSIFIED_EXTREME_VWAP_BLOCK_PCT", "2.25")
            ):
                reason = (
                    f"unclassified extended entry blocked: setup_label={setup_label}, "
                    f"vwap_dist={session_vwap_dist_pct:.3f}%"
                )
                return self._reject_current_signal(
                    symbol=symbol,
                    action=action,
                    price=price,
                    account_state=account_state,
                    dedupe_key=dedupe_key,
                    category="unclassified_extended_entry",
                    reason=reason,
                )

            if setup_label == "unclassified_transition" and session_vwap_dist_pct >= float(
                os.getenv("UNCLASSIFIED_EXTENDED_VWAP_CAP_PCT", "1.50")
            ):
                cap_pct = float(os.getenv("UNCLASSIFIED_EXTENDED_SIZE_CAP_PCT", "0.35"))
                self.deps.apply_size_cap(
                    account_state,
                    cap_pct=cap_pct,
                    state_key="unclassified_extended_size_cap",
                    payload={
                        "cap_pct": cap_pct,
                        "setup_label": setup_label,
                        "session_distance_from_vwap_pct": session_vwap_dist_pct,
                        "reason": (
                            "unclassified_transition above extended VWAP threshold; "
                            "cap size until repeated evidence proves this setup"
                        ),
                    },
                )
                self.deps.log.warning(
                    f"Unclassified extended setup size cap for {symbol}: "
                    f"vwap={session_vwap_dist_pct:.3f}% cap={cap_pct:.2f}%"
                )

            if (
                setup_label == "late_strength_near_vwap_risk"
                and session_return_pct > 1.5
                and session_vwap_dist_pct > 1.0
                and session_m15_pct < 0
                and session_m30_pct < 0
            ):
                reason = (
                    f"late rollover entry blocked: setup_label={setup_label}, "
                    f"session_return={session_return_pct:.3f}%, "
                    f"vwap_dist={session_vwap_dist_pct:.3f}%, "
                    f"15m={session_m15_pct:.3f}%, "
                    f"30m={session_m30_pct:.3f}%"
                )
                return self._reject_current_signal(
                    symbol=symbol,
                    action=action,
                    price=price,
                    account_state=account_state,
                    dedupe_key=dedupe_key,
                    category="late_rollover_entry",
                    reason=reason,
                )

        if action == "buy":
            second_look_blocks = self.deps.count_second_look_blocks_today(symbol)
            setup_label = setup_obs.get("setup_label") or ""

            prediction_gate = account_state.get("prediction_gate") or {}
            prediction_decision = (
                prediction_gate.get("prediction_decision")
                or prediction_gate.get("decision")
                or ""
            )

            session_score = float(account_state.get("session_trend_score") or 0)
            session_return_pct = float(account_state.get("session_return_pct") or 0)

            if (
                second_look_blocks >= int(os.getenv("LATE_QUOTE_DELAY_MIN_BLOCKS", "3"))
                and setup_label in {"unclassified_transition", "balanced_transition_state"}
                and str(prediction_decision).lower() in {"watch", "neutral", "none", ""}
                and session_return_pct >= float(
                    os.getenv("LATE_QUOTE_DELAY_MIN_SESSION_RETURN_PCT", "0.75")
                )
                and session_score <= float(os.getenv("LATE_QUOTE_DELAY_MAX_SESSION_SCORE", "5"))
            ):
                reason = (
                    f"late entry after repeated second-look quote blocks: "
                    f"second_look_blocks={second_look_blocks}, "
                    f"setup_label={setup_label}, "
                    f"prediction_decision={prediction_decision}, "
                    f"session_score={session_score:.1f}, "
                    f"session_return={session_return_pct:.3f}%"
                )
                return self._reject_current_signal(
                    symbol=symbol,
                    action=action,
                    price=price,
                    account_state=account_state,
                    dedupe_key=dedupe_key,
                    category="late_after_quote_delay",
                    reason=reason,
                )

        return StageResult()

    def check_sell_discipline(self, *, symbol, action, price, account_state, dedupe_key, existing_position):
        if action != "sell" or not existing_position:
            return StageResult()

        try:
            avg_entry = float(existing_position.get("avg_entry") or 0)
            current_price = float(existing_position.get("current_price") or price or 0)
            qty = float(existing_position.get("qty") or 0)

            min_profit_to_sell_pct = 0.50

            if avg_entry > 0 and current_price > 0 and qty > 0:
                unrealized_pct = (current_price - avg_entry) / avg_entry * 100

                trend = self.deps.trend_table.get(symbol) or {}
                direction = trend.get("direction")
                strength = trend.get("strength")
                consecutive_count = int(trend.get("consecutive_count") or 0)

                confirmed_bearish = (
                    direction == "bearish"
                    and strength in ("developing", "confirmed")
                    and consecutive_count >= 2
                )

                if 0 <= unrealized_pct < min_profit_to_sell_pct and not confirmed_bearish:
                    reason = (
                        f"profit {unrealized_pct:.2f}% below minimum sell threshold "
                        f"{min_profit_to_sell_pct:.2f}% without confirmed bearish pressure "
                        f"(trend={direction}/{strength}, count={consecutive_count})"
                    )
                    return self._reject_current_signal(
                        symbol=symbol,
                        action=action,
                        price=price,
                        account_state=account_state,
                        dedupe_key=dedupe_key,
                        category="sell_profit_threshold",
                        reason=reason,
                    )

                if -0.75 < unrealized_pct < 0 and not confirmed_bearish:
                    reason = (
                        f"small red position {unrealized_pct:.2f}% without confirmed bearish sell pressure "
                        f"(trend={direction}/{strength}, count={consecutive_count})"
                    )
                    return self._reject_current_signal(
                        symbol=symbol,
                        action=action,
                        price=price,
                        account_state=account_state,
                        dedupe_key=dedupe_key,
                        category="sell_discipline",
                        reason=reason,
                    )

        except Exception as exc:
            self.deps.log.warning(
                f"Sell discipline check failed for {symbol}; fail-open for SELL safety: {exc}"
            )

        return StageResult()

    def run_macro_position_gate(self, **kwargs):
        outcome = run_macro_position_gate(
            macro_position_count_floor=self.deps.macro_position_count_floor,
            get_latest_session_momentum=self.deps.get_latest_session_momentum,
            session_momentum_is_fresh=self.deps.session_momentum_is_fresh,
            weakest_position_context=self.deps.weakest_position_context,
            evaluate_buy_opportunity=self.deps.evaluate_buy_opportunity,
            required_buy_confirmations=self.deps.required_buy_confirmations,
            try_portfolio_rotation=self.deps.try_portfolio_rotation,
            get_account_state=self.deps.get_account_state,
            sleep=self.deps.sleep,
            log=self.deps.log,
            **{k: v for k, v in kwargs.items() if k != "rejection_adapter"},
        )
        if outcome.rejected and outcome.approval:
            return StageResult(
                rejected=kwargs["rejection_adapter"].reject_approval_decision(
                    outcome.approval
                )
            )
        return StageResult()

    def run_trend_confirmation_gate(self, **kwargs):
        outcome = run_trend_confirmation_gate(
            required_buy_confirmations=self.deps.required_buy_confirmations,
            required_sell_confirmations=self.deps.required_sell_confirmations,
            is_fast_lane_buy_flip=self.deps.is_fast_lane_buy_flip,
            is_fast_lane_sell_flip=self.deps.is_fast_lane_sell_flip,
            market_open_minutes=self.deps.market_open_minutes,
            open_momentum_fast_lane_enabled=self.deps.open_momentum_fast_lane_enabled,
            iex_thin_symbols=self.deps.iex_thin_symbols,
            adaptive_buy_confirmation_enabled=self.deps.adaptive_buy_confirmation_enabled,
            log=self.deps.log,
            **{
                k: v
                for k, v in kwargs.items()
                if k not in ("price", "account_state", "rejection_adapter")
            },
        )
        if outcome.rejected and outcome.approval:
            return StageResult(
                rejected=kwargs["rejection_adapter"].reject_approval_decision(
                    outcome.approval
                )
            )
        return StageResult()

    def run_entry_sanity_gates(self, **kwargs):
        outcome = run_entry_sanity_gates(
            apply_market_bias_context=self.deps.apply_market_bias_context,
            **{
                k: v
                for k, v in kwargs.items()
                if k not in ("price", "rejection_adapter")
            },
        )
        if outcome.rejected and outcome.approval:
            return StageResult(
                rejected=kwargs["rejection_adapter"].reject_approval_decision(
                    outcome.approval
                )
            )
        return StageResult()

    def run_prediction_bias_session_gate(self, **kwargs):
        outcome = run_prediction_session_tape_gates(
            execution_mode=self.deps.execution_mode,
            evaluate_signal_quality_gate=self.deps.evaluate_signal_quality_gate,
            get_cached_prediction=self.deps.get_cached_prediction,
            ml_prediction_bucket=self.deps.ml_prediction_bucket,
            evaluate_buy_opportunity=self.deps.evaluate_buy_opportunity,
            required_buy_confirmations=self.deps.required_buy_confirmations,
            live_bias_override=self.deps.live_bias_override,
            evaluate_session_momentum_gate=self.deps.evaluate_session_momentum_gate,
            apply_size_cap=self.deps.apply_size_cap,
            env_float=self.deps.env_float,
            prediction_soft_avoid_min_sample_size=(
                self.deps.prediction_soft_avoid_min_sample_size
            ),
            enforce_prediction_blocks=self.deps.enforce_prediction_blocks,
            enforce_prediction_watch_in_cash=self.deps.enforce_prediction_watch_in_cash,
            prediction_gate_mode=self.deps.prediction_gate_mode,
            ml_authority_config=self.deps.ml_authority_config,
            is_cash_mode=self.deps.is_cash_mode,
            enforce_session_momentum_gate=self.deps.enforce_session_momentum_gate,
            is_degraded_setup=self.deps.is_degraded_setup,
            log=self.deps.log,
            **{k: v for k, v in kwargs.items() if k not in ("price", "rejection_adapter")},
        )
        if outcome.rejected and outcome.approval:
            return StageResult(
                rejected=kwargs["rejection_adapter"].reject_approval_decision(
                    outcome.approval
                )
            )
        return StageResult()

    def run_intra_session_tape_degradation_gate(self, **kwargs):
        outcome = run_intra_session_tape_degradation_gate(
            enabled=self.deps.intra_session_tape_degradation_enabled,
            start_hour_et=self.deps.intra_session_tape_degradation_start_hour_et,
            min_setup_score=self.deps.intra_session_tape_degradation_min_setup_score,
            et_timezone=self.deps.et_timezone,
            log=self.deps.log,
            **{k: v for k, v in kwargs.items() if k not in ("price", "rejection_adapter")},
        )
        if outcome.rejected and outcome.approval:
            return StageResult(
                rejected=kwargs["rejection_adapter"].reject_approval_decision(
                    outcome.approval
                )
            )
        return StageResult()

    def run_final_approval_gates(self, **kwargs):
        outcome = run_final_approval_gates(
            signal=kwargs["data"],
            symbol=kwargs["symbol"],
            action=kwargs["action"],
            price=kwargs["price"],
            account_state=kwargs["account_state"],
            context_runtime=kwargs["context_runtime"],
            score_buy_opportunity=self.deps.score_buy_opportunity,
            memory_for_signal=self.deps.memory_for_signal,
            build_intelligence_context=self.deps.build_intelligence_context,
            evaluate_decision_policy=self.deps.evaluate_decision_policy,
            public_decision_policy_config=self.deps.public_decision_policy_config,
            decision_policy_live_authority_enabled=(
                self.deps.decision_policy_live_authority_enabled
            ),
            decision_policy_live_block_enabled=self.deps.decision_policy_live_block_enabled,
            decision_policy_live_size_down_enabled=(
                self.deps.decision_policy_live_size_down_enabled
            ),
            build_conviction_stack=self.deps.build_conviction_stack,
            ml_prediction_bucket=self.deps.ml_prediction_bucket,
            compute_dominant_limiter=self.deps.compute_dominant_limiter,
            log_event=self.deps.log_event,
            log=self.deps.log,
        )
        if outcome.rejected and outcome.approval:
            return ApprovalGateResult(
                rejected=kwargs["rejection_adapter"].reject_approval_decision(
                    outcome.approval
                ),
                claude_account_state=outcome.claude_account_state,
            )
        return ApprovalGateResult(
            claude_account_state=outcome.claude_account_state
        )

    def run_claude_and_confidence(self, **kwargs):
        def medium_confidence_override(*, decision, account_state):
            symbol = kwargs["symbol"]
            return self.deps.medium_confidence_override(
                symbol=symbol,
                action=kwargs["action"],
                decision=decision,
                account_state=account_state,
                trend=self.deps.trend_table.get(symbol) or {},
                setup_obs=account_state.get("setup_observation") or {},
            )

        outcome = run_claude_and_confidence(
            signal=kwargs["data"],
            symbol=kwargs["symbol"],
            action=kwargs["action"],
            account_state=kwargs["account_state"],
            claude_account_state=kwargs["claude_account_state"],
            weekly_symbol_performance=self.deps.weekly_symbol_performance,
            medium_confidence_override=medium_confidence_override,
            evaluate_signal=self.deps.evaluate_signal,
            cash_safe_mode=self.deps.is_cash_safe_mode(),
            market_bias=self.deps.market_bias.get(kwargs["symbol"]) or {},
            tape_exception_enabled=self.deps.tape_exception_enabled,
            log=self.deps.log,
        )
        if outcome.rejected and outcome.approval:
            return ClaudeStageResult(
                rejected=kwargs["rejection_adapter"].reject_approval_decision(
                    outcome.approval
                )
            )
        return ClaudeStageResult(decision=outcome.decision)

    def run_approved_order_path(self, **kwargs):
        rejected = execute_approved_order(
            signal=kwargs["data"],
            symbol=kwargs["symbol"],
            action=kwargs["action"],
            price=kwargs["price"],
            account_state=kwargs["account_state"],
            dedupe_key=kwargs["dedupe_key"],
            current_et=kwargs["current_et"],
            decision=kwargs["decision"],
            execution_mode=self.deps.execution_mode,
            apply_final_sizing=self.deps.apply_final_sizing,
            apply_buy_opportunity_sizing=self.deps.apply_buy_opportunity_sizing,
            execute_order_func=self.deps.execute_order,
            pre_order_safety_check=self.deps.pre_order_safety_check,
            one_bar_confirmation_hold=self.deps.one_bar_confirmation_hold,
            make_client_order_id=self.deps.make_client_order_id,
            place_order=self.deps.place_order,
            execution_rejection_decision=execution_rejection_decision,
            deterministic_rejection=deterministic_rejection,
            rejection_adapter=kwargs["rejection_adapter"],
            log_trade=self.deps.log_trade,
            record_webhook_status=self.deps.record_webhook_status,
            write_cooldown=self.deps.write_cooldown,
            write_recent_sell=self.deps.write_recent_sell,
            last_order=self.deps.last_order,
            last_sell=self.deps.last_sell,
            log=self.deps.log,
        )
        if rejected:
            return StageResult(rejected=True)
        return StageResult()
