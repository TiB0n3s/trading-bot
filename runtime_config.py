import os


VALID_EXECUTION_MODES = {"paper", "cash_safe", "cash_full", "dry_run"}

EXECUTION_MODE = os.getenv("EXECUTION_MODE", "paper").strip().lower()
if EXECUTION_MODE not in VALID_EXECUTION_MODES:
    EXECUTION_MODE = "paper"


def _env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


def _env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, default))
    except (TypeError, ValueError):
        return default


LIVE_TRADING_ENABLED = _env_bool("LIVE_TRADING_ENABLED", False)

ALPACA_PAPER_BASE_URL = os.getenv(
    "ALPACA_PAPER_BASE_URL",
    "https://paper-api.alpaca.markets",
)

ALPACA_LIVE_BASE_URL = os.getenv(
    "ALPACA_LIVE_BASE_URL",
    "https://api.alpaca.markets",
)

CASH_SAFE_SYMBOLS = {
    s.strip().upper()
    for s in os.getenv("CASH_SAFE_SYMBOLS", "SPY,QQQ,AAPL,MSFT,NVDA").split(",")
    if s.strip()
}

CASH_SAFE_MAX_OPEN_POSITIONS = _env_int("CASH_SAFE_MAX_OPEN_POSITIONS", 3)

CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY = _env_int(
    "CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY",
    1,
)

MAX_LIVE_ORDER_DOLLARS = _env_float("MAX_LIVE_ORDER_DOLLARS", 500.0)

CASH_SAFE_MAX_ORDER_DOLLARS = _env_float(
    "CASH_SAFE_MAX_ORDER_DOLLARS",
    min(MAX_LIVE_ORDER_DOLLARS, 500.0),
)

DECISION_POLICY_AUTHORITY_MODE = os.getenv(
    "DECISION_POLICY_AUTHORITY_MODE", "paper_only"
).strip().lower()
if DECISION_POLICY_AUTHORITY_MODE not in {"disabled", "paper_only", "all_modes"}:
    DECISION_POLICY_AUTHORITY_MODE = "paper_only"

DECISION_POLICY_LIVE_BLOCK = _env_bool("DECISION_POLICY_LIVE_BLOCK", True)
DECISION_POLICY_LIVE_SIZE_DOWN = _env_bool("DECISION_POLICY_LIVE_SIZE_DOWN", True)

ML_AUTHORITY_MODES = {
    "observe_only_compare",
    "size_down_only",
    "paper_block",
    "live_block",
}
ML_AUTHORITY_MODE = os.getenv("ML_AUTHORITY_MODE", "observe_only_compare").strip().lower()
if ML_AUTHORITY_MODE not in ML_AUTHORITY_MODES:
    ML_AUTHORITY_MODE = "observe_only_compare"

ML_AUTHORITY_MIN_SAMPLE_SIZE = _env_int("ML_AUTHORITY_MIN_SAMPLE_SIZE", 20)
ML_AUTHORITY_MIN_CONFIDENCE = os.getenv("ML_AUTHORITY_MIN_CONFIDENCE", "medium").strip().lower()
if ML_AUTHORITY_MIN_CONFIDENCE not in {"unknown", "low", "medium", "high"}:
    ML_AUTHORITY_MIN_CONFIDENCE = "medium"

# 0 disables recency enforcement. Keep this disabled by default until all
# prediction producers write a consistent point-in-time timestamp.
ML_AUTHORITY_MAX_AGE_SECONDS = _env_int("ML_AUTHORITY_MAX_AGE_SECONDS", 0)
ML_AUTHORITY_SIZE_CAP_PCT = _env_float("ML_AUTHORITY_SIZE_CAP_PCT", 0.80)


def is_cash_mode() -> bool:
    return EXECUTION_MODE in {"cash_safe", "cash_full"}


def is_cash_safe_mode() -> bool:
    return EXECUTION_MODE == "cash_safe"


def get_alpaca_base_url() -> str:
    if is_cash_mode():
        return ALPACA_LIVE_BASE_URL
    return ALPACA_PAPER_BASE_URL


def max_order_dollars() -> float:
    if EXECUTION_MODE == "cash_safe":
        return CASH_SAFE_MAX_ORDER_DOLLARS
    if EXECUTION_MODE == "cash_full":
        return MAX_LIVE_ORDER_DOLLARS
    return float("inf")


def decision_policy_live_authority_enabled() -> bool:
    if DECISION_POLICY_AUTHORITY_MODE == "disabled":
        return False
    if DECISION_POLICY_AUTHORITY_MODE == "paper_only":
        return EXECUTION_MODE in {"paper", "dry_run"}
    return True


def public_decision_policy_config() -> dict:
    authority_enabled = decision_policy_live_authority_enabled()
    return {
        "authority_mode": DECISION_POLICY_AUTHORITY_MODE,
        "authority_enabled_for_execution_mode": authority_enabled,
        "live_block_enabled": DECISION_POLICY_LIVE_BLOCK and authority_enabled,
        "live_size_down_enabled": DECISION_POLICY_LIVE_SIZE_DOWN and authority_enabled,
        "default_authority_mode": "paper_only",
        "paper_only_under_review": True,
        "can_increase_size": False,
        "can_submit_orders": False,
        "hard_gate_behavior": (
            "Decision policy mirrors hard-gate context from account_state for replay/audit. "
            "It must not override app hard gates."
        ),
    }


def public_ml_authority_config() -> dict:
    return {
        "authority_mode": ML_AUTHORITY_MODE,
        "allowed_modes": sorted(ML_AUTHORITY_MODES),
        "min_sample_size": ML_AUTHORITY_MIN_SAMPLE_SIZE,
        "min_confidence": ML_AUTHORITY_MIN_CONFIDENCE,
        "max_age_seconds": ML_AUTHORITY_MAX_AGE_SECONDS,
        "size_cap_pct": ML_AUTHORITY_SIZE_CAP_PCT,
        "negative_decisions": ["avoid", "block", "caution"],
        "can_increase_size": False,
        "default_authority_mode": "observe_only_compare",
    }


def public_runtime_config() -> dict:
    return {
        "execution_mode": EXECUTION_MODE,
        "live_trading_enabled": LIVE_TRADING_ENABLED,
        "alpaca_base_url_type": "live" if is_cash_mode() else "paper",
        "cash_safe_symbols": sorted(CASH_SAFE_SYMBOLS) if is_cash_safe_mode() else None,
        "cash_safe_max_open_positions": CASH_SAFE_MAX_OPEN_POSITIONS if is_cash_safe_mode() else None,
        "cash_safe_max_new_buys_per_symbol_per_day": (
            CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY if is_cash_safe_mode() else None
        ),
        "max_live_order_dollars": MAX_LIVE_ORDER_DOLLARS if is_cash_mode() else None,
        "cash_safe_max_order_dollars": CASH_SAFE_MAX_ORDER_DOLLARS if is_cash_safe_mode() else None,
        "decision_policy": public_decision_policy_config(),
        "ml_authority": public_ml_authority_config(),
    }
