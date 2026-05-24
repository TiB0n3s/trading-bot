"""Stable rejection category constants for trading-bot reporting.

These constants are intentionally boring and durable. They are meant to keep
analytics, logs, and future refactors from depending on shifting free-text
rejection reasons.
"""

MARKET_HOURS = "market_hours"
DAILY_LOSS_LIMIT = "daily_loss_limit"
SYMBOL_NOT_APPROVED = "symbol_not_approved"
MACRO_RISK = "macro_risk"
MARKET_CONTEXT_AVOID = "market_context_avoid"
SETUP_POLICY = "setup_policy"
TREND_CONFIRMATION = "trend_confirmation"
COOLDOWN = "cooldown"
SELL_TO_BUY_CHURN = "sell_to_buy_churn"
AFFORDABILITY = "affordability"
PRICE_SANITY = "price_sanity"
BROKER_REJECTED = "broker_rejected"
CLAUDE_REJECTED = "claude_rejected"
PREDICTION_GATE = "prediction_gate"
DUPLICATE_SIGNAL = "duplicate_signal"
ORDER_QTY_ZERO = "order_qty_zero"
UNKNOWN_ERROR = "unknown_error"

ALL_REJECTION_CATEGORIES = {
    MARKET_HOURS,
    DAILY_LOSS_LIMIT,
    SYMBOL_NOT_APPROVED,
    MACRO_RISK,
    MARKET_CONTEXT_AVOID,
    SETUP_POLICY,
    TREND_CONFIRMATION,
    COOLDOWN,
    SELL_TO_BUY_CHURN,
    AFFORDABILITY,
    PRICE_SANITY,
    BROKER_REJECTED,
    CLAUDE_REJECTED,
    PREDICTION_GATE,
    DUPLICATE_SIGNAL,
    ORDER_QTY_ZERO,
    UNKNOWN_ERROR,
}
