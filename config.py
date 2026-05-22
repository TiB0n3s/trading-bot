from symbols_config import APPROVED_SYMBOLS, PRICE_RANGES
import os
"""
Central trading bot configuration.

Keep static strategy constants here so app.py, parsers, reports, and docs
do not drift over time.
"""

# Market window in Eastern Time, expressed as minutes after midnight.
MARKET_OPEN_MINUTES = 9 * 60 + 30
MARKET_CLOSE_MINUTES = 16 * 60

DAILY_LOSS_LIMIT_PCT = -3.0
MAX_BUYS_PER_SYMBOL_PER_DAY = 2
MAX_OPEN_POSITIONS = 12
WEBHOOK_DEDUPE_SECONDS = 60

# Feature flag: when true, BUY trend confirmation uses _required_buy_confirmations()
# instead of the fixed 3-BUY rule. Enable with:
# ADAPTIVE_BUY_CONFIRMATION_ENABLED=true
ADAPTIVE_BUY_CONFIRMATION_ENABLED = os.environ.get(
    "ADAPTIVE_BUY_CONFIRMATION_ENABLED",
    "false",
).lower().strip() in ("1", "true", "yes", "on")

# Market-alignment mapping used for macro/trend context.
# This is observe-only at first; app.py can use it for /debug/symbol before it becomes a gate.
SYMBOL_MARKET_ALIGNMENT = {
    # Broad index / ETFs
    "SPY":   {"cluster": "broad_index", "benchmark": "SPY"},
    "QQQ":   {"cluster": "mega_cap_tech", "benchmark": "QQQ"},
    "IWM":   {"cluster": "small_caps", "benchmark": "IWM"},
    "GLD":   {"cluster": "gold_hedge", "benchmark": "GLD"},

    # Mega-cap tech / AI leadership
    "AAPL":  {"cluster": "mega_cap_tech", "benchmark": "QQQ"},
    "MSFT":  {"cluster": "mega_cap_tech", "benchmark": "QQQ"},
    "NVDA":  {"cluster": "semiconductors", "benchmark": "QQQ"},
    "AMD":   {"cluster": "semiconductors", "benchmark": "QQQ"},
    "AVGO":  {"cluster": "semiconductors", "benchmark": "QQQ"},
    "META":  {"cluster": "mega_cap_tech", "benchmark": "QQQ"},
    "GOOGL": {"cluster": "mega_cap_tech", "benchmark": "QQQ"},
    "ORCL":  {"cluster": "enterprise_software", "benchmark": "QQQ"},

    # Retail / consumer
    "TSCO":  {"cluster": "consumer_retail", "benchmark": "SPY"},
    "TSLA":  {"cluster": "high_beta_growth", "benchmark": "QQQ"},

    # Energy
    "CVX":   {"cluster": "energy", "benchmark": "SPY"},
    "XOM":   {"cluster": "energy", "benchmark": "SPY"},

    # AI infrastructure / power / industrial
    "CRDO":  {"cluster": "ai_infrastructure", "benchmark": "QQQ"},
    "GEV":   {"cluster": "ai_power", "benchmark": "SPY"},
    "BE":    {"cluster": "ai_power", "benchmark": "SPY"},
    "CAT":   {"cluster": "industrials", "benchmark": "SPY"},
    "VRT":   {"cluster": "ai_infrastructure", "benchmark": "QQQ"},

    # Defense / aerospace
    "RKLB":  {"cluster": "space_defense", "benchmark": "SPY"},
    "RTX":   {"cluster": "defense", "benchmark": "SPY"},
    "LMT":   {"cluster": "defense", "benchmark": "SPY"},
    "HWM":   {"cluster": "defense_industrial", "benchmark": "SPY"},

    # Biotech
    "VRTX":  {"cluster": "biotech_quality", "benchmark": "SPY"},
    "MRNA":  {"cluster": "biotech_speculative", "benchmark": "IWM"},
    "CRSP":  {"cluster": "biotech_speculative", "benchmark": "IWM"},
    "V":    {"cluster": "payments", "benchmark": "SPY"},
    "MA":   {"cluster": "payments", "benchmark": "SPY"},
    "LLY":  {"cluster": "large_cap_healthcare", "benchmark": "SPY"},
    "LIN":  {"cluster": "industrials", "benchmark": "SPY"},
    "GE":   {"cluster": "aerospace_industrials", "benchmark": "SPY"},

    # New additions — May 2026, batch 2
    "ASML": {"cluster": "semiconductors", "benchmark": "QQQ"},
    "NFLX": {"cluster": "high_beta_growth", "benchmark": "QQQ"},
    "CRM":  {"cluster": "enterprise_software", "benchmark": "QQQ"},
    "COST": {"cluster": "consumer_retail", "benchmark": "SPY"},
    "KO":   {"cluster": "consumer_staples", "benchmark": "SPY"},
    "ABBV": {"cluster": "large_cap_healthcare", "benchmark": "SPY"},
    "MRK":  {"cluster": "large_cap_healthcare", "benchmark": "SPY"},
    "UNH":  {"cluster": "large_cap_healthcare", "benchmark": "SPY"},
}

