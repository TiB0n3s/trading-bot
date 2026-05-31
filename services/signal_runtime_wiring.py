"""Signal pipeline dependency wiring.

This module owns the transitional runtime wiring while app.py is being reduced
to a composition shell. It receives the runtime module explicitly to avoid a
container -> app.py import cycle and to preserve existing test patch points.
"""

from __future__ import annotations

from typing import Any

from services.live_signal_processor import (
    LiveSignalProcessor,
    LiveSignalProcessorDeps,
    build_context_runtime as live_build_context_runtime,
    build_runtime_state as live_build_runtime_state,
)
from services.signal_pipeline import SignalPipelineDeps


def build_live_signal_processor(*, container: Any, runtime: Any) -> LiveSignalProcessor:
    return LiveSignalProcessor(
        LiveSignalProcessorDeps(
            log=runtime.logger,
            log_rejection=(
                lambda symbol, action, category, reason, price=None, account_state=None: runtime._trade_audit_recorder().record_rejection(
                    symbol=symbol,
                    action=action,
                    category=category,
                    reason=reason,
                    price=price,
                    account_state=account_state,
                )
            ),
            record_webhook_status=(
                lambda **kwargs: runtime._trade_audit_recorder().record_webhook_status(
                    **kwargs
                )
            ),
            parse_stale_signal=runtime._is_signal_stale,
            is_cash_safe_mode=runtime.is_cash_safe_mode,
            cash_safe_symbols=runtime.CASH_SAFE_SYMBOLS,
            cash_safe_max_open_positions=runtime.CASH_SAFE_MAX_OPEN_POSITIONS,
            cash_safe_max_new_buys_per_symbol_per_day=runtime.CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY,
            cash_safe_buys_today=container.repositories.trades.cash_safe_buys_today,
            symbol_override_block=runtime._symbol_override_block,
            enforce_setup_policy_blocks=runtime.ENFORCE_SETUP_POLICY_BLOCKS,
            apply_size_cap=runtime.apply_size_cap,
            trend_table=runtime._trend_table,
            env_float=runtime._env_float,
            is_unrecognized_setup_label=runtime.is_unrecognized_setup_label,
            count_second_look_blocks_today=runtime._count_second_look_blocks_today,
            apply_market_bias_context=runtime.context_builder_apply_market_bias_context,
            update_trend_history=runtime._update_trend_history,
            sell_continuation_delay_reason=runtime._sell_continuation_delay_reason,
            hydrate_pre_macro_context=runtime._hydrate_pre_macro_context,
            hydrate_session_context=runtime._hydrate_session_context,
            hydrate_buy_momentum_context=runtime._hydrate_buy_momentum_context,
            hydrate_strategy_context=runtime._hydrate_strategy_context,
            macro_position_count_floor=runtime.MACRO_POSITION_COUNT_FLOOR,
            get_latest_session_momentum=runtime.get_latest_session_momentum,
            session_momentum_is_fresh=runtime._session_momentum_is_fresh,
            weakest_position_context=runtime._get_weakest_position_context,
            evaluate_buy_opportunity=runtime.evaluate_buy_opportunity,
            required_buy_confirmations=runtime._required_buy_confirmations,
            try_portfolio_rotation=runtime._try_portfolio_rotation,
            get_account_state=runtime.get_mock_account_state,
            sleep=runtime.time.sleep,
            required_sell_confirmations=runtime._required_sell_confirmations,
            is_fast_lane_buy_flip=runtime.is_fast_lane_buy_flip,
            is_fast_lane_sell_flip=runtime.is_fast_lane_sell_flip,
            market_open_minutes=runtime.MARKET_OPEN_MINUTES,
            open_momentum_fast_lane_enabled=runtime.OPEN_MOMENTUM_FAST_LANE_ENABLED,
            iex_thin_symbols=runtime.IEX_THIN_SYMBOLS,
            adaptive_buy_confirmation_enabled=runtime.ADAPTIVE_BUY_CONFIRMATION_ENABLED,
            execution_mode=runtime.EXECUTION_MODE,
            evaluate_signal_quality_gate=runtime.evaluate_signal_quality_gate,
            get_cached_prediction=runtime.get_cached_prediction,
            ml_prediction_bucket=runtime._ml_prediction_bucket,
            live_bias_override=runtime.entry_policy.live_bias_override,
            evaluate_session_momentum_gate=runtime.entry_policy.evaluate_session_momentum_gate,
            prediction_soft_avoid_min_sample_size=runtime.PREDICTION_SOFT_AVOID_MIN_SAMPLE_SIZE,
            enforce_prediction_blocks=runtime.ENFORCE_PREDICTION_BLOCKS,
            enforce_prediction_watch_in_cash=runtime.ENFORCE_PREDICTION_WATCH_IN_CASH,
            prediction_gate_mode=runtime.PREDICTION_GATE_MODE,
            ml_authority_config=runtime.public_ml_authority_config(),
            is_cash_mode=runtime.is_cash_mode,
            enforce_session_momentum_gate=runtime.ENFORCE_SESSION_MOMENTUM_GATE,
            is_degraded_setup=runtime.is_degraded_setup,
            intra_session_tape_degradation_enabled=runtime.INTRA_SESSION_TAPE_DEGRADATION_ENABLED,
            intra_session_tape_degradation_start_hour_et=runtime.INTRA_SESSION_TAPE_DEGRADATION_START_HOUR_ET,
            intra_session_tape_degradation_min_setup_score=runtime.INTRA_SESSION_TAPE_DEGRADATION_MIN_SETUP_SCORE,
            et_timezone=runtime.ET,
            score_buy_opportunity=runtime.score_buy_opportunity,
            memory_for_signal=runtime.memory_for_signal,
            build_intelligence_context=runtime.build_intelligence_context,
            evaluate_decision_policy=runtime.evaluate_decision_policy,
            public_decision_policy_config=runtime.public_decision_policy_config,
            decision_policy_live_authority_enabled=runtime.decision_policy_live_authority_enabled,
            decision_policy_live_block_enabled=runtime.DECISION_POLICY_LIVE_BLOCK,
            decision_policy_live_size_down_enabled=runtime.DECISION_POLICY_LIVE_SIZE_DOWN,
            build_conviction_stack=runtime.build_conviction_stack,
            compute_dominant_limiter=runtime.sizing_policy.compute_dominant_limiter,
            log_event=runtime.log_event,
            weekly_symbol_performance=runtime._weekly_symbol_performance,
            medium_confidence_override=runtime._allow_medium_confidence_momentum_override,
            evaluate_signal=runtime.evaluate_signal,
            tape_exception_enabled=runtime.TAPE_EXCEPTION_ENABLED,
            market_bias=runtime._market_bias,
            apply_final_sizing=runtime.apply_final_sizing,
            apply_buy_opportunity_sizing=lambda **kwargs: (
                runtime.sizing_policy.apply_buy_opportunity_sizing(
                    **kwargs,
                    log=runtime.logger,
                )
            ),
            execute_order=runtime.execute_order,
            pre_order_safety_check=runtime._pre_order_safety_check,
            one_bar_confirmation_hold=runtime._one_bar_confirmation_hold,
            make_client_order_id=runtime._make_client_order_id,
            place_order=container.broker_service.place_order,
            log_trade=(
                lambda signal, decision, order, account_state=None: runtime._trade_audit_recorder().record_execution(
                    signal=signal,
                    decision=decision,
                    order=order,
                    account_state=account_state,
                )
            ),
            write_cooldown=runtime._write_cooldown,
            write_recent_sell=runtime._write_recent_sell,
            last_order=runtime._last_order,
            last_sell=runtime._last_sell,
        )
    )


def build_signal_pipeline_deps(*, container: Any, runtime: Any) -> SignalPipelineDeps:
    return SignalPipelineDeps(
        live_signal_processor=build_live_signal_processor(
            container=container,
            runtime=runtime,
        ),
        build_runtime_state=(
            lambda signal_context: live_build_runtime_state(
                signal_context,
                load_market_context=runtime._load_market_context,
                get_account_state=runtime.get_mock_account_state,
            )
        ),
        build_context_runtime=(
            lambda runtime_state: live_build_context_runtime(
                runtime_state,
                build_signal_context=runtime.build_signal_context_runtime,
                context_deps=runtime._context_assembly_deps(),
            )
        ),
        evaluate_preflight=runtime._evaluate_preflight,
        log_rejection=(
            lambda symbol, action, category, reason, price=None, account_state=None: runtime._trade_audit_recorder().record_rejection(
                symbol=symbol,
                action=action,
                category=category,
                reason=reason,
                price=price,
                account_state=account_state,
            )
        ),
        mark_webhook_event_status=(
            lambda dedupe_key, status, **kwargs: runtime._trade_audit_recorder().record_webhook_status(
                dedupe_key=dedupe_key,
                status=status,
                **kwargs,
            )
        ),
        logger=runtime.logger,
    )
