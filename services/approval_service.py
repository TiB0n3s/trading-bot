"""Approval stage interfaces for the signal pipeline.

This module decides approval state only. It does not submit orders or write DB
rows; callers own persistence and side effects.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from services.signal_models import ApprovalResult, DecisionContext


@dataclass(frozen=True)
class ApprovalDecision:
    approved: bool
    source: str
    confidence: str | None
    reason: str
    category: str | None = None
    claude_payload: dict[str, Any] | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class LegacyClaudeOutcome:
    rejected: bool = False
    approval: ApprovalDecision | None = None
    decision: dict[str, Any] | None = None


@dataclass(frozen=True)
class LegacyApprovalGateOutcome:
    rejected: bool = False
    approval: ApprovalDecision | None = None
    claude_account_state: dict[str, Any] | None = None


@dataclass(frozen=True)
class LegacyStageOutcome:
    rejected: bool = False
    approval: ApprovalDecision | None = None
    metadata: dict[str, Any] = field(default_factory=dict)


def deterministic_rejection(
    *,
    category: str,
    reason: str,
    source: str = "deterministic",
    confidence: str | None = None,
    metadata: dict[str, Any] | None = None,
) -> ApprovalDecision:
    return ApprovalDecision(
        approved=False,
        source=source,
        confidence=confidence,
        reason=reason,
        category=category,
        claude_payload=None,
        metadata=metadata or {},
    )


def setup_policy_rejection(reason: str, metadata: dict[str, Any] | None = None) -> ApprovalDecision:
    return deterministic_rejection(
        category="setup_policy",
        reason=reason,
        metadata=metadata,
    )


def trend_confirmation_rejection(reason: str, metadata: dict[str, Any] | None = None) -> ApprovalDecision:
    return deterministic_rejection(
        category="trend_confirmation",
        reason=reason,
        metadata=metadata,
    )


def session_momentum_rejection(reason: str, metadata: dict[str, Any] | None = None) -> ApprovalDecision:
    return deterministic_rejection(
        category="session_momentum_gate",
        reason=reason,
        metadata=metadata,
    )


def prediction_gate_rejection(reason: str, metadata: dict[str, Any] | None = None) -> ApprovalDecision:
    return deterministic_rejection(
        category="prediction_gate",
        reason=reason,
        metadata=metadata,
    )


def live_bias_rejection(category: str, reason: str, metadata: dict[str, Any] | None = None) -> ApprovalDecision:
    return deterministic_rejection(
        category=category,
        reason=reason,
        metadata=metadata,
    )


def strategy_memory_rejection(reason: str, metadata: dict[str, Any] | None = None) -> ApprovalDecision:
    return deterministic_rejection(
        category="strategy_memory",
        reason=reason,
        metadata=metadata,
    )


def opportunity_score_rejection(reason: str, metadata: dict[str, Any] | None = None) -> ApprovalDecision:
    return deterministic_rejection(
        category="opportunity_score",
        reason=reason,
        metadata=metadata,
    )


def decision_policy_rejection(reason: str, metadata: dict[str, Any] | None = None) -> ApprovalDecision:
    return deterministic_rejection(
        category="decision_policy",
        reason=reason,
        metadata=metadata,
    )


def execution_rejection_decision(outcome: Any) -> ApprovalDecision:
    return deterministic_rejection(
        category=getattr(outcome, "rejection_category", None) or "order_path_exception",
        reason=(
            getattr(outcome, "rejection_reason", None)
            or getattr(outcome, "failure_reason", None)
            or "execution rejected"
        ),
        source="execution",
        metadata=getattr(outcome, "metadata", None) or {},
    )


def normalize_claude_decision(
    *,
    action: str,
    decision: dict[str, Any],
) -> dict[str, Any]:
    normalized = dict(decision or {})
    reason_text = str(normalized.get("reason", "")).lower()
    defer_phrases = (
        "defer",
        "wait",
        "hold off",
        "lacks sufficient conviction",
        "not enough conviction",
        "until momentum",
        "momentum turns rising",
    )

    if action == "buy" and normalized.get("approved") and any(
        phrase in reason_text for phrase in defer_phrases
    ):
        normalized["approved"] = False
        normalized["confidence"] = "low"
        normalized["position_size_pct"] = 0
        normalized["reason"] = (
            "Rejected by consistency guard: Claude reason indicated deferral/wait "
            "despite approved=true."
        )
        normalized["_consistency_guard_triggered"] = True
    return normalized


def evaluate_approval_decision(
    *,
    signal: dict[str, Any],
    action: str,
    claude_account_state: dict[str, Any],
    evaluate_signal: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    cash_safe_mode: bool,
    market_bias: dict[str, Any] | None,
    account_state: dict[str, Any],
    medium_confidence_override: Callable[..., tuple[bool, str]],
    tape_exception_enabled: bool,
) -> ApprovalDecision:
    raw_decision = evaluate_signal(signal, claude_account_state)
    decision = normalize_claude_decision(action=action, decision=raw_decision)
    confidence = decision.get("confidence")
    reason = str(decision.get("reason", ""))

    if action == "buy" and cash_safe_mode and confidence != "high":
        return ApprovalDecision(
            approved=False,
            source="confidence_gate",
            confidence=confidence,
            reason=f"cash_safe requires confidence=high; got {confidence} (reason: {reason})",
            category="cash_safe_confidence",
            claude_payload=decision,
            metadata={"raw_decision": raw_decision},
        )

    if action == "buy" and confidence == "low":
        return ApprovalDecision(
            approved=False,
            source="confidence_gate",
            confidence=confidence,
            reason=f"Claude returned confidence=low (reason: {reason})",
            category="confidence_gate",
            claude_payload=decision,
            metadata={"raw_decision": raw_decision},
        )

    bias_entry = market_bias or {}
    if action == "buy" and confidence != "high" and bias_entry.get("bias") == "neutral":
        momentum_ctx = account_state.get("momentum") or {}
        tape = account_state.get("tape") or {}
        tape_label = tape.get("label")
        vol_state = momentum_ctx.get("volume_state")
        momentum_state = momentum_ctx.get("momentum_state")
        tape_exception = tape_exception_enabled and (
            momentum_state == "accelerating"
            and vol_state in ("elevated", "surge")
            and tape_label == "clean_momentum"
        )
        if not tape_exception:
            medium_ok, medium_reason = medium_confidence_override(
                decision=decision,
                account_state=account_state,
            )
            if not medium_ok:
                return ApprovalDecision(
                    approved=False,
                    source="confidence_gate",
                    confidence=confidence,
                    reason=(
                        f"neutral_bias requires confidence=high; got {confidence} "
                        f"(reason: {reason})"
                    ),
                    category="confidence_gate",
                    claude_payload=decision,
                    metadata={
                        "gate": "neutral_bias",
                        "momentum_state": momentum_state,
                        "volume_state": vol_state,
                        "tape_label": tape_label,
                        "override_reason": medium_reason,
                    },
                )
            account_state["confidence_gate_medium_override"] = {
                "gate": "neutral_bias",
                "reason": medium_reason,
            }

    if action == "buy" and confidence != "high" and bias_entry.get("entry_quality") == "conditional":
        medium_ok, medium_reason = medium_confidence_override(
            decision=decision,
            account_state=account_state,
        )
        if not medium_ok:
            return ApprovalDecision(
                approved=False,
                source="confidence_gate",
                confidence=confidence,
                reason=(
                    f"conditional_entry_quality requires confidence=high; got {confidence} "
                    f"(reason: {reason})"
                ),
                category="confidence_gate",
                claude_payload=decision,
                metadata={
                    "gate": "conditional_entry_quality",
                    "override_reason": medium_reason,
                },
            )
        account_state["confidence_gate_medium_override"] = {
            "gate": "conditional_entry_quality",
            "reason": medium_reason,
        }

    return ApprovalDecision(
        approved=bool(decision.get("approved")),
        source="claude",
        confidence=confidence,
        reason=reason,
        claude_payload=decision,
        metadata={"raw_decision": raw_decision},
    )


class ApprovalService:
    def evaluate(self, context: DecisionContext) -> ApprovalResult:
        return ApprovalResult(approved=True, reason="deferred_to_live_signal_processor")


def run_legacy_claude_and_confidence(
    *,
    signal: dict[str, Any],
    symbol: str,
    action: str,
    account_state: dict[str, Any],
    claude_account_state: dict[str, Any],
    weekly_symbol_performance: Callable[[str], dict[str, Any]],
    medium_confidence_override: Callable[..., tuple[bool, str]],
    evaluate_signal: Callable[[dict[str, Any], dict[str, Any]], dict[str, Any]],
    cash_safe_mode: bool,
    market_bias: dict[str, Any] | None,
    tape_exception_enabled: bool,
    log: Any,
) -> LegacyClaudeOutcome:
    weekly_perf = weekly_symbol_performance(symbol)
    account_state["weekly_symbol_performance"] = weekly_perf
    claude_account_state["weekly_symbol_performance"] = weekly_perf

    approval_decision = evaluate_approval_decision(
        signal=signal,
        action=action,
        claude_account_state=claude_account_state,
        evaluate_signal=evaluate_signal,
        cash_safe_mode=cash_safe_mode,
        market_bias=market_bias or {},
        account_state=account_state,
        medium_confidence_override=medium_confidence_override,
        tape_exception_enabled=tape_exception_enabled,
    )
    decision = dict(approval_decision.claude_payload or {})

    if (approval_decision.metadata or {}).get("raw_decision", {}).get("approved") and decision.get(
        "_consistency_guard_triggered"
    ):
        log.warning(
            f"Decision consistency guard flipped {symbol} BUY to rejected: "
            f"approved=true but reason indicated deferral"
        )

    if approval_decision.category:
        log.warning(
            f"{approval_decision.category} rejected {symbol} {action.upper()}: "
            f"{approval_decision.reason}"
        )
        return LegacyClaudeOutcome(rejected=True, approval=approval_decision)

    return LegacyClaudeOutcome(decision=decision)


def run_legacy_macro_position_gate(
    *,
    symbol: str,
    action: str,
    price: Any,
    account_state: dict[str, Any],
    context_runtime: Any,
    current_et: Any,
    macro_risk: dict[str, Any],
    macro_position_count_floor: float,
    get_latest_session_momentum: Callable[[str], dict[str, Any] | None],
    session_momentum_is_fresh: Callable[[dict[str, Any]], bool],
    weakest_position_context: Callable[[dict[str, Any]], dict[str, Any] | None],
    evaluate_buy_opportunity: Callable[..., dict[str, Any]],
    required_buy_confirmations: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    try_portfolio_rotation: Callable[..., tuple[bool, str, dict[str, Any]]],
    get_account_state: Callable[[], dict[str, Any]],
    sleep: Callable[[float], None],
    log: Any,
) -> LegacyStageOutcome:
    if action != "buy":
        return LegacyStageOutcome()

    if macro_risk.get("block_new_buys"):
        return LegacyStageOutcome(
            rejected=True,
            approval=deterministic_rejection(
                category="macro_risk",
                reason=macro_risk.get("reason", "macro regime blocks new buys"),
                metadata=macro_risk,
            ),
        )

    max_new_positions = macro_risk.get("max_new_positions", 8)
    open_count = account_state.get("open_position_count", 0)
    open_positions = account_state.get("open_positions") or []
    if open_positions:
        effective_count = sum(
            1 for position in open_positions
            if float(position.get("market_value") or 0) >= macro_position_count_floor
        )
    else:
        effective_count = open_count

    if effective_count < max_new_positions:
        return LegacyStageOutcome()

    candidate_session = None
    try:
        candidate_session = get_latest_session_momentum(symbol)
        if candidate_session and not session_momentum_is_fresh(candidate_session):
            candidate_session = None
    except Exception as exc:
        log.warning(f"macro_position_limit session lookup failed for {symbol}: {exc}")
        candidate_session = None

    if candidate_session:
        account_state["session_momentum"] = candidate_session

    def session_value(key: str, fallback_key: str | None = None):
        if candidate_session and candidate_session.get(key) is not None:
            return candidate_session.get(key)
        if fallback_key:
            return account_state.get(fallback_key)
        return None

    candidate_session_score = session_value("trend_score", "session_trend_score")
    candidate_session_label = session_value("trend_label", "session_trend_label")
    candidate_return = session_value("session_return_pct", "session_return_pct")
    candidate_vwap = session_value(
        "distance_from_vwap_pct",
        "session_distance_from_vwap_pct",
    )

    weakest = weakest_position_context(account_state)

    if weakest:
        replacement_hint = "observe_only"
        reason = (
            f"open_position_count={open_count} effective={effective_count} >= macro max_new_positions={max_new_positions}; "
            f"candidate={symbol} session={candidate_session_label}/{candidate_session_score} "
            f"return={candidate_return}% vwap_dist={candidate_vwap}%; "
            f"weakest_holding={weakest.get('symbol')} "
            f"plpc={weakest.get('unrealized_plpc'):.2f}% "
            f"replacement_hint={replacement_hint}"
        )
    else:
        reason = (
            f"open_position_count={open_count} effective={effective_count} >= macro max_new_positions={max_new_positions}; "
            f"candidate={symbol} session={candidate_session_label}/{candidate_session_score} "
            f"return={candidate_return}% vwap_dist={candidate_vwap}%; "
            f"weakest_holding=unknown"
        )

    try:
        macro_limit_opportunity_obs = context_runtime.build_buy_opportunity_observation(
            trend=context_runtime.deps.trend_table.get(symbol) or {},
            bias_entry=context_runtime.deps.market_bias.get(symbol) or {},
            evaluate_buy_opportunity=evaluate_buy_opportunity,
            required_buy_confirmations=required_buy_confirmations,
            log_prefix="BUY opportunity macro-limit",
        )
        macro_limit_buy_opportunity = macro_limit_opportunity_obs.data
        macro_buy_score = macro_limit_buy_opportunity.get("buy_opportunity_score")
        macro_buy_rec = macro_limit_buy_opportunity.get("buy_opportunity_recommendation")
        reason = (
            f"{reason}; buy_score={macro_buy_score}; "
            f"buy_rec={macro_buy_rec}"
        )
    except Exception as exc:
        log.warning(f"BUY opportunity macro-limit scoring failed for {symbol}: {exc}")

    rotated, rotation_reason, rotation_info = try_portfolio_rotation(
        symbol,
        price,
        account_state,
        current_et,
    )

    if rotated:
        account_state["portfolio_rotation"] = rotation_info
        log.warning(
            f"Portfolio rotation submitted for {symbol}: {rotation_reason}; "
            "waiting briefly for Alpaca position state to refresh"
        )

        sleep(2)
        refreshed_state = get_account_state() or {}
        refreshed_open_count = refreshed_state.get("open_position_count", open_count)

        if refreshed_open_count < max_new_positions:
            account_state.update(refreshed_state)
            log.warning(
                f"Portfolio rotation freed a slot for {symbol}: "
                f"open_position_count {open_count} -> {refreshed_open_count}; "
                "continuing BUY pipeline"
            )
            return LegacyStageOutcome()

        pending_reason = (
            f"rotation_pending: {rotation_reason}; "
            f"open_position_count still {refreshed_open_count} >= "
            f"macro max_new_positions={max_new_positions}; original_reason={reason}"
        )
        log.warning(f"Portfolio rotation pending for {symbol}: {pending_reason}")
        return LegacyStageOutcome(
            rejected=True,
            approval=deterministic_rejection(
                category="portfolio_rotation_pending",
                reason=pending_reason,
                metadata={"rotation_info": rotation_info},
            ),
        )

    reason = f"{reason}; rotation_not_taken={rotation_reason}"
    return LegacyStageOutcome(
        rejected=True,
        approval=deterministic_rejection(
            category="macro_position_limit",
            reason=reason,
            metadata={
                "open_position_count": open_count,
                "effective_count": effective_count,
                "max_new_positions": max_new_positions,
                "rotation_reason": rotation_reason,
            },
        ),
    )


def run_legacy_trend_confirmation_gate(
    *,
    symbol: str,
    action: str,
    current_et: Any,
    context_runtime: Any,
    required_buy_confirmations: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    required_sell_confirmations: Callable[[str, dict[str, Any] | None], dict[str, Any]],
    is_fast_lane_buy_flip: Callable[..., bool],
    is_fast_lane_sell_flip: Callable[..., bool],
    market_open_minutes: int,
    open_momentum_fast_lane_enabled: bool,
    iex_thin_symbols: set[str],
    adaptive_buy_confirmation_enabled: bool,
    log: Any,
) -> LegacyStageOutcome:
    if action not in ("buy", "sell"):
        return LegacyStageOutcome()

    trend_obs = context_runtime.build_trend_confirmation_observation(
        current_et=current_et,
        required_buy_confirmations=required_buy_confirmations,
        required_sell_confirmations=required_sell_confirmations,
        is_fast_lane_buy_flip=is_fast_lane_buy_flip,
        is_fast_lane_sell_flip=is_fast_lane_sell_flip,
        market_open_minutes=market_open_minutes,
        open_momentum_fast_lane_enabled=open_momentum_fast_lane_enabled,
        iex_thin_symbols=iex_thin_symbols,
    )
    trend = trend_obs.data
    trend_confirmation = trend_obs.confirmation
    direction = trend_obs.direction
    strength = trend_obs.strength
    consecutive_count = trend_obs.consecutive_count
    last_signal = trend_obs.last_signal

    if action == "buy":
        adaptive_confirmation = trend_confirmation.get("adaptive_confirmation") or {}
        required = int(trend_confirmation.get("required_confirmations") or 3)

        if direction != "bullish" or last_signal != "buy":
            reason = (
                f"direction={direction} "
                f"last_signal={last_signal} "
                f"required={required}"
            )
            log.info(f"Trend confirmation BUY observe-only for {symbol}: {reason}")

        fast_lane_buy_flip = bool(trend_confirmation.get("fast_lane_buy_flip"))
        open_momentum_fast_lane = bool(
            trend_confirmation.get("open_momentum_fast_lane")
        )

        log.info(
            f"Trend confirmation BUY for {symbol}: "
            f"required={required} "
            f"count={consecutive_count} "
            f"direction={direction} "
            f"strength={strength} "
            f"last_signal={last_signal} "
            f"flip_event={trend.get('flip_event')} "
            f"fast_lane_buy_flip={fast_lane_buy_flip} "
            f"open_momentum_fast_lane={open_momentum_fast_lane} "
            f"(elapsed={trend_confirmation.get('session_elapsed_minutes')}min "
            f"momentum={trend_confirmation.get('momentum_state')} "
            f"vol={trend_confirmation.get('volume_state')} "
            f"vol_ok={trend_confirmation.get('volume_ok')} "
            f"iex_thin={trend_confirmation.get('iex_thin')} "
            f"bias={trend_confirmation.get('bias')}) "
            f"adaptive_reason={adaptive_confirmation.get('reason')}"
        )
        if open_momentum_fast_lane and consecutive_count < required:
            log.info(
                f"Open-momentum fast lane granted for {symbol}: "
                f"elapsed={trend_confirmation.get('session_elapsed_minutes')}min "
                f"count={consecutive_count} "
                f"momentum={trend_confirmation.get('momentum_state')} "
                f"vol={trend_confirmation.get('volume_state')} "
                f"iex_thin={trend_confirmation.get('iex_thin')}"
            )

        if not (fast_lane_buy_flip or open_momentum_fast_lane) and consecutive_count < required:
            reason = (
                f"consecutive_buy_count={consecutive_count} "
                f"< required={required} "
                f"strength={strength} "
                f"flip_event={trend.get('flip_event')} "
                f"adaptive_reason={adaptive_confirmation.get('reason')}"
            )

            if adaptive_buy_confirmation_enabled:
                return LegacyStageOutcome(
                    rejected=True,
                    approval=trend_confirmation_rejection(
                        reason,
                        metadata=trend_confirmation,
                    ),
                )
            log.info(f"Trend confirmation BUY observe-only for {symbol}: {reason}")

        return LegacyStageOutcome()

    sell_confirmation = trend_confirmation.get("sell_confirmation") or {}
    required = int(trend_confirmation.get("required_confirmations") or 2)

    if direction != "bearish" or last_signal != "sell":
        reason = (
            f"direction={direction} "
            f"last_signal={last_signal} "
            f"required={required}"
        )
        return LegacyStageOutcome(
            rejected=True,
            approval=trend_confirmation_rejection(
                reason,
                metadata=trend_confirmation,
            ),
        )

    fast_lane_sell_flip = bool(trend_confirmation.get("fast_lane_sell_flip"))

    log.info(
        f"Trend confirmation SELL for {symbol}: "
        f"required={required} "
        f"count={consecutive_count} "
        f"direction={direction} "
        f"strength={strength} "
        f"last_signal={last_signal} "
        f"flip_event={trend.get('flip_event')} "
        f"fast_lane_sell_flip={fast_lane_sell_flip} "
        f"sell_reason={sell_confirmation.get('reason')}"
    )

    if not fast_lane_sell_flip and consecutive_count < required:
        reason = (
            f"consecutive_sell_count={consecutive_count} "
            f"< required={required} "
            f"strength={strength} "
            f"flip_event={trend.get('flip_event')}"
        )
        return LegacyStageOutcome(
            rejected=True,
            approval=trend_confirmation_rejection(
                reason,
                metadata=trend_confirmation,
            ),
        )

    return LegacyStageOutcome()


def run_legacy_final_approval_gates(
    *,
    signal: dict[str, Any],
    symbol: str,
    action: str,
    price: Any,
    account_state: dict[str, Any],
    context_runtime: Any,
    score_buy_opportunity: Callable[[str, dict[str, Any], dict[str, Any]], dict[str, Any]],
    memory_for_signal: Callable[[str, dict[str, Any]], dict[str, Any]],
    build_intelligence_context: Callable[..., dict[str, Any]],
    evaluate_decision_policy: Callable[..., dict[str, Any]],
    public_decision_policy_config: Callable[[], dict[str, Any]],
    decision_policy_live_authority_enabled: Callable[[], bool],
    decision_policy_live_block_enabled: bool,
    decision_policy_live_size_down_enabled: bool,
    build_conviction_stack: Callable[..., Any],
    ml_prediction_bucket: Callable[[Any], str],
    compute_dominant_limiter: Callable[..., Any],
    log_event: Callable[..., Any],
    log: Any,
) -> LegacyApprovalGateOutcome:
    claude_account_state = dict(account_state)

    if action == "buy":
        try:
            buying_power_for_affordability = float(account_state.get("buying_power") or 0)
            signal_price_f = float(price or 0)

            if buying_power_for_affordability > 0 and signal_price_f > 0 and buying_power_for_affordability < signal_price_f:
                reason = (
                    f"buying_power ${buying_power_for_affordability:.2f} cannot buy 1 share "
                    f"at signal price ${signal_price_f:.2f}"
                )
                return LegacyApprovalGateOutcome(
                    rejected=True,
                    approval=deterministic_rejection(
                        category="affordability",
                        reason=reason,
                        metadata={
                            "buying_power": buying_power_for_affordability,
                            "signal_price": signal_price_f,
                        },
                    ),
                    claude_account_state=claude_account_state,
                )

        except Exception as exc:
            log.warning(f"Affordability gate skipped for {symbol} BUY due to error: {exc}")

    if action == "buy":
        opportunity = score_buy_opportunity(symbol, signal, account_state)
        account_state["opportunity_score"] = opportunity
        claude_account_state["opportunity_score"] = opportunity

        strategy_memory = memory_for_signal(symbol, opportunity)
        account_state["strategy_memory"] = strategy_memory
        claude_account_state["strategy_memory"] = strategy_memory

        learned_min_score = strategy_memory.get("min_setup_score")
        if isinstance(learned_min_score, int):
            raw_score = opportunity.get("score")
            try:
                score_f = float(raw_score)
            except Exception:
                score_f = None

            normalized_score = score_f

            log.info(
                f"STRATEGY_MEMORY {symbol} BUY: "
                f"recommendation={strategy_memory.get('recommendation')} "
                f"learned_min_score={learned_min_score} "
                f"opportunity_score={raw_score} "
                f"normalized_score={normalized_score} "
                f"reason={strategy_memory.get('reason')}"
            )

            if (
                normalized_score is not None
                and strategy_memory.get("recommendation") in ("caution", "avoid")
                and normalized_score < learned_min_score
            ):
                reason = (
                    f"strategy memory tightened {symbol}: "
                    f"recommendation={strategy_memory.get('recommendation')} "
                    f"normalized_score={normalized_score:.1f} < learned_min_score={learned_min_score}; "
                    f"{strategy_memory.get('reason')}"
                )
                log.warning(
                    f"Strategy memory gate blocked {symbol} BUY before Claude: {reason}"
                )
                return LegacyApprovalGateOutcome(
                    rejected=True,
                    approval=strategy_memory_rejection(
                        reason,
                        metadata={
                            "strategy_memory": strategy_memory,
                            "opportunity_score": opportunity,
                        },
                    ),
                    claude_account_state=claude_account_state,
                )

        log.info(
            f"Opportunity score for {symbol} BUY: "
            f"score={opportunity.get('score')} bucket={opportunity.get('bucket')} "
            f"decision={opportunity.get('decision')} "
            f"size_multiplier={opportunity.get('size_multiplier')} "
            f"reasons={opportunity.get('reason_codes')}"
        )

        if opportunity.get("decision") == "block":
            reason = opportunity.get("summary", "opportunity score blocked setup")
            log.warning(
                f"Opportunity score gate blocked {symbol} BUY before Claude: {reason}"
            )
            return LegacyApprovalGateOutcome(
                rejected=True,
                approval=opportunity_score_rejection(reason, metadata=opportunity),
                claude_account_state=claude_account_state,
            )

    intelligence_context = build_intelligence_context(
        symbol=symbol,
        action=action,
        account_state=account_state,
    )
    account_state["intelligence_context"] = intelligence_context
    claude_account_state["intelligence_context"] = intelligence_context

    summary = intelligence_context.get("summary") or {}
    log.info(
        f"INTELLIGENCE_CONTEXT {symbol} {action.upper()}: "
        f"recommended_action={summary.get('recommended_action')} "
        f"supports={summary.get('support_count')} "
        f"risks={summary.get('risk_count')} "
        f"primary_supports={summary.get('primary_supports')} "
        f"primary_risks={summary.get('primary_risks')}"
    )

    decision_policy = evaluate_decision_policy(
        symbol=symbol,
        action=action,
        intelligence_context=intelligence_context,
        account_state=account_state,
    )
    account_state["decision_policy"] = decision_policy
    claude_account_state["decision_policy"] = decision_policy
    decision_policy_config = public_decision_policy_config()
    account_state["decision_policy_authority"] = decision_policy_config
    claude_account_state["decision_policy_authority"] = decision_policy_config

    log.info(
        f"DECISION_POLICY {symbol} {action.upper()}: "
        f"decision={decision_policy.get('decision')} "
        f"size_multiplier={decision_policy.get('size_multiplier')} "
        f"reason={decision_policy.get('reason')} "
        f"risks={decision_policy.get('risks')} "
        f"supports={decision_policy.get('supports')}"
    )

    decision_policy_authority_enabled = decision_policy_live_authority_enabled()
    decision_policy_live_block = (
        decision_policy_live_block_enabled and decision_policy_authority_enabled
    )
    decision_policy_live_size_down = (
        decision_policy_live_size_down_enabled and decision_policy_authority_enabled
    )

    if (
        action == "buy"
        and decision_policy_live_block
        and decision_policy.get("decision") == "block"
    ):
        reason = decision_policy.get("reason", "decision policy blocked setup")
        log.warning(
            f"Decision policy gate blocked {symbol} BUY before Claude: {reason}"
        )
        return LegacyApprovalGateOutcome(
            rejected=True,
            approval=decision_policy_rejection(reason, metadata=decision_policy),
            claude_account_state=claude_account_state,
        )
    elif action == "buy" and decision_policy.get("decision") == "block":
        log.warning(
            f"Decision policy block observed but not enforced for {symbol} BUY: "
            f"authority_enabled={decision_policy_authority_enabled} "
            f"live_block_enabled={decision_policy_live_block_enabled} "
            f"mode={decision_policy_config.get('authority_mode')} "
            f"reason={decision_policy.get('reason')}"
        )

    if (
        action == "buy"
        and decision_policy_live_size_down
        and decision_policy.get("decision") == "size_down"
    ):
        try:
            size_multiplier = float(decision_policy.get("size_multiplier") or 1.0)
        except Exception:
            size_multiplier = 1.0

        size_multiplier = max(0.0, min(1.0, size_multiplier))

        current_limit = None
        for key in ("max_position_size_pct", "position_size_pct"):
            try:
                val = claude_account_state.get(key)
                if val is not None:
                    current_limit = float(val)
                    break
            except Exception:
                pass

        if current_limit is None:
            current_limit = 2.0

        reduced_limit = round(current_limit * size_multiplier, 4)

        account_state["decision_policy_size_down"] = {
            "enabled": True,
            "original_position_size_pct": current_limit,
            "reduced_position_size_pct": reduced_limit,
            "size_multiplier": size_multiplier,
            "reason": decision_policy.get("reason"),
        }
        claude_account_state["decision_policy_size_down"] = account_state[
            "decision_policy_size_down"
        ]
        claude_account_state["max_position_size_pct"] = reduced_limit
        claude_account_state["decision_policy_max_position_size_pct"] = reduced_limit

        log.warning(
            f"DECISION_POLICY_SIZE_DOWN {symbol} BUY: "
            f"original_position_size_pct={current_limit} "
            f"size_multiplier={size_multiplier} "
            f"reduced_position_size_pct={reduced_limit} "
            f"reason={decision_policy.get('reason')}"
        )

        log_event(
            event_type="DECISION_POLICY_SIZE_DOWN",
            symbol=symbol,
            action=action,
            decision="size_down",
            severity="medium",
            reason=decision_policy.get("reason"),
            source="app.py",
            payload={
                "decision_policy": decision_policy,
                "original_position_size_pct": current_limit,
                "reduced_position_size_pct": reduced_limit,
                "size_multiplier": size_multiplier,
            },
        )
    elif action == "buy" and decision_policy.get("decision") == "size_down":
        log.info(
            f"Decision policy size_down observed but not enforced for {symbol} BUY: "
            f"authority_enabled={decision_policy_authority_enabled} "
            f"live_size_down_enabled={decision_policy_live_size_down_enabled} "
            f"mode={decision_policy_config.get('authority_mode')} "
            f"reason={decision_policy.get('reason')}"
        )

    if action == "buy":
        build_conviction_stack(
            action=action,
            account_state=account_state,
            ml_prediction_bucket=ml_prediction_bucket,
            compute_dominant_limiter=compute_dominant_limiter,
        )

    built_context = context_runtime.refresh(
        intelligence_context=intelligence_context,
        claude_account_state=claude_account_state,
    )
    claude_account_state = built_context.claude_account_state

    summary = built_context.summary
    log.info(
        f"Decision context for {symbol} {action.upper()}: "
        f"setup={summary.get('setup_label')}/"
        f"{summary.get('setup_policy_action')} "
        f"prediction={summary.get('prediction_score')}/"
        f"{summary.get('prediction_decision')} "
        f"session={summary.get('session_trend_label')}/"
        f"{summary.get('session_trend_score')} "
        f"session_gate={summary.get('session_gate_severity')}/"
        f"{summary.get('session_gate_would_block')} "
        f"effective_bias={summary.get('effective_bias')}"
    )

    if action == "buy":
        log.info(
            f"Conviction stack for {symbol} BUY: "
            f"buy_opp={account_state['conviction_stack']['buy_opportunity']} "
            f"strategy={account_state['conviction_stack']['strategy_score']:.0f} "
            f"session={account_state['conviction_stack']['session_severity']} "
            f"ml_bucket={account_state['conviction_stack']['ml_bucket']} "
            f"cap={account_state['conviction_stack']['effective_cap_pct']} "
            f"dominant={account_state['dominant_limiter']}"
        )

    return LegacyApprovalGateOutcome(claude_account_state=claude_account_state)
