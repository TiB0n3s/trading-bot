"""Canonical rejection category registry.

Every category emitted by live signal processing should be listed here.  The
root-level ``rejection_categories.py`` module re-exports this registry for
backward compatibility with older report imports.
"""

from __future__ import annotations

MARKET_HOURS = "market_hours"
DAILY_LOSS_LIMIT = "daily_loss_limit"
CIRCUIT_BREAKER = "circuit_breaker"
SYMBOL_NOT_APPROVED = "symbol_not_approved"
MACRO_RISK = "macro_risk"
MACRO_POSITION_LIMIT = "macro_position_limit"
MARKET_CONTEXT_AVOID = "market_context_avoid"
MARKET_BIAS_AVOID = "market_bias_avoid"
SETUP_POLICY = "setup_policy"
TREND_CONFIRMATION = "trend_confirmation"
COOLDOWN = "cooldown"
SELL_TO_BUY_CHURN = "sell_to_buy_churn"
CHURN_WINDOW = "churn_window"
CHURN_PRICE = "churn_price"
AFFORDABILITY = "affordability"
PRICE_SANITY = "price_sanity"
PAYLOAD_VALIDATION = "payload_validation"
BROKER_REJECTED = "broker_rejected"
CLAUDE_REJECTED = "claude_rejected"
CLAUDE_PARSE_ERROR = "claude_parse_error"
CLAUDE_ENGINE_ERROR = "claude_engine_error"
PREDICTION_GATE = "prediction_gate"
DUPLICATE_SIGNAL = "duplicate_signal"
DUPLICATE_WEBHOOK = "duplicate_webhook"
ORDER_QTY_ZERO = "order_qty_zero"
UNKNOWN_ERROR = "unknown_error"

GHOST_SELL = "ghost_sell"
SYMBOL_OVERRIDE = "symbol_override"
DAILY_SYMBOL_BUY_LIMIT = "daily_symbol_buy_limit"
SESSION_TRADE_COUNT = "session_trade_count"
EXPOSURE_CAP = "exposure_cap"
CORRELATION_CAP = "correlation_cap"
SELL_PROFIT_THRESHOLD = "sell_profit_threshold"
SELL_DISCIPLINE = "sell_discipline"
LATE_ROLLOVER_ENTRY = "late_rollover_entry"
LATE_AFTER_QUOTE_DELAY = "late_after_quote_delay"
CASH_SAFE_SYMBOL = "cash_safe_symbol"
CASH_SAFE_POSITION_LIMIT = "cash_safe_position_limit"
CASH_SAFE_DAILY_SYMBOL_LIMIT = "cash_safe_daily_symbol_limit"
CASH_SAFE_CONFIDENCE = "cash_safe_confidence"
FUNDAMENTAL_SCORE = "fundamental_score"
CHASE_PREVENTION = "chase_prevention"
SESSION_MOMENTUM_GATE = "session_momentum_gate"
OPPORTUNITY_SCORE = "opportunity_score"
STRATEGY_MEMORY = "strategy_memory"
DECISION_POLICY = "decision_policy"
CONFIDENCE_GATE = "confidence_gate"
SECOND_LOOK = "second_look"
ONE_BAR_CONFIRMATION_HOLD = "one_bar_confirmation_hold"
ORDER_PATH_EXCEPTION = "order_path_exception"
STALE_SIGNAL = "stale_signal"
ADDON_MOMENTUM_GATE = "addon_momentum_gate"
INTRA_SESSION_TAPE_DEGRADATION = "intra_session_tape_degradation"
LIVE_BIAS_DOWNGRADE = "live_bias_downgrade"
PORTFOLIO_ROTATION_PENDING = "portfolio_rotation_pending"
SELL_CONTINUATION_CHECK = "sell_continuation_check"
SOFT_AVOID_PREDICTION_GATE = "soft_avoid_prediction_gate"
AUTHORITY_MATRIX = "authority_matrix"
EXECUTION_QUALITY = "execution_quality"
HISTORICAL_BAR_META_LABEL_VETO = "historical_bar_meta_label_veto"
LIVE_CIRCUIT_BREAKER = "live_circuit_breaker"
LAYERED_MODEL_AUTHORITY_VETO = "layered_model_authority_veto"
SLIPPAGE_KELLY = "slippage_kelly"

ALL_REJECTION_CATEGORIES = {
    MARKET_HOURS,
    DAILY_LOSS_LIMIT,
    CIRCUIT_BREAKER,
    SYMBOL_NOT_APPROVED,
    MACRO_RISK,
    MACRO_POSITION_LIMIT,
    MARKET_CONTEXT_AVOID,
    MARKET_BIAS_AVOID,
    SETUP_POLICY,
    TREND_CONFIRMATION,
    COOLDOWN,
    SELL_TO_BUY_CHURN,
    CHURN_WINDOW,
    CHURN_PRICE,
    AFFORDABILITY,
    PRICE_SANITY,
    PAYLOAD_VALIDATION,
    BROKER_REJECTED,
    CLAUDE_REJECTED,
    CLAUDE_PARSE_ERROR,
    CLAUDE_ENGINE_ERROR,
    PREDICTION_GATE,
    DUPLICATE_SIGNAL,
    DUPLICATE_WEBHOOK,
    ORDER_QTY_ZERO,
    UNKNOWN_ERROR,
    GHOST_SELL,
    SYMBOL_OVERRIDE,
    DAILY_SYMBOL_BUY_LIMIT,
    SESSION_TRADE_COUNT,
    EXPOSURE_CAP,
    CORRELATION_CAP,
    SELL_PROFIT_THRESHOLD,
    SELL_DISCIPLINE,
    LATE_ROLLOVER_ENTRY,
    LATE_AFTER_QUOTE_DELAY,
    CASH_SAFE_SYMBOL,
    CASH_SAFE_POSITION_LIMIT,
    CASH_SAFE_DAILY_SYMBOL_LIMIT,
    CASH_SAFE_CONFIDENCE,
    FUNDAMENTAL_SCORE,
    CHASE_PREVENTION,
    SESSION_MOMENTUM_GATE,
    OPPORTUNITY_SCORE,
    STRATEGY_MEMORY,
    DECISION_POLICY,
    CONFIDENCE_GATE,
    SECOND_LOOK,
    ONE_BAR_CONFIRMATION_HOLD,
    ORDER_PATH_EXCEPTION,
    STALE_SIGNAL,
    ADDON_MOMENTUM_GATE,
    INTRA_SESSION_TAPE_DEGRADATION,
    LIVE_BIAS_DOWNGRADE,
    PORTFOLIO_ROTATION_PENDING,
    SELL_CONTINUATION_CHECK,
    SOFT_AVOID_PREDICTION_GATE,
    AUTHORITY_MATRIX,
    EXECUTION_QUALITY,
    HISTORICAL_BAR_META_LABEL_VETO,
    LIVE_CIRCUIT_BREAKER,
    LAYERED_MODEL_AUTHORITY_VETO,
    SLIPPAGE_KELLY,
}

LEGACY_CATEGORY_ALIASES: dict[str, str] = {
    "daily_loss_limit": CIRCUIT_BREAKER,
    "duplicate_signal": DUPLICATE_WEBHOOK,
    "sell_to_buy_churn": CHURN_WINDOW,
    "claude_rejected": CONFIDENCE_GATE,
    "broker_rejected": SECOND_LOOK,
}


def normalize_category(category: str | None) -> str:
    """Return a stable rejection category for persisted/reportable reasons."""
    raw = str(category or "").strip().lower()
    if not raw:
        return UNKNOWN_ERROR
    return LEGACY_CATEGORY_ALIASES.get(raw, raw)


def format_rejection_reason(category: str | None, reason: str | None) -> str:
    """Format rejection_reason as a stable category prefix plus free-text reason."""
    stable_category = normalize_category(category)
    clean_reason = str(reason or "").strip()
    if clean_reason.startswith(f"{stable_category}:"):
        return clean_reason
    return f"{stable_category}: {clean_reason}" if clean_reason else f"{stable_category}:"


def reason_category(rejection_reason: str | None) -> str:
    """Extract and normalize the category prefix from a persisted rejection."""
    reason = str(rejection_reason or "").strip()
    if not reason:
        return UNKNOWN_ERROR
    prefix = reason.split(":", 1)[0]
    return normalize_category(prefix)
