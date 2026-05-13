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
    }
