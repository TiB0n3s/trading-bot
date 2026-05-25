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
PAYLOAD_VALIDATION = "payload_validation"
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
    PAYLOAD_VALIDATION,
    BROKER_REJECTED,
    CLAUDE_REJECTED,
    PREDICTION_GATE,
    DUPLICATE_SIGNAL,
    ORDER_QTY_ZERO,
    UNKNOWN_ERROR,
}

LEGACY_CATEGORY_ALIASES: dict[str, str] = {}


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
