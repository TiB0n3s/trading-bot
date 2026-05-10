"""
Central trading bot configuration.

Keep static strategy constants here so app.py, parsers, reports, and docs
do not drift over time.
"""

APPROVED_SYMBOLS = {
    "AAPL", "SPY", "QQQ", "MSFT", "NVDA", "ORCL", "TSCO", "TSLA",
    "META", "AMD", "CVX", "XOM", "GOOGL", "GLD", "IWM",
    "AVGO", "CRDO", "GEV", "BE", "CAT", "VRT",
    "RKLB", "RTX", "LMT", "HWM",
    "VRTX", "MRNA", "CRSP",
}

# Market window in Eastern Time, expressed as minutes after midnight.
MARKET_OPEN_MINUTES = 9 * 60 + 30
MARKET_CLOSE_MINUTES = 16 * 60

DAILY_LOSS_LIMIT_PCT = -3.0
MAX_BUYS_PER_SYMBOL_PER_DAY = 2
WEBHOOK_DEDUPE_SECONDS = 60

# (min, max) expected price ranges; webhook signals outside ±20% of this range are rejected.
PRICE_RANGES = {
    "AAPL": (150,  500),
    "SPY":  (400,  700),
    "QQQ":  (400,  900),
    "MSFT": (200,  600),
    "NVDA": ( 80,  600),
    "ORCL": ( 80,  300),
    "TSCO": ( 20,   80),
    "TSLA": (100,  800),
    "META": (200, 1000),
    "AMD":  ( 50,  600),
    "CVX":  (100,  260),
    "XOM":  ( 80,  215),
    "GOOGL": (250, 550),
    "GLD":   (250, 550),
    "IWM":   (180, 350),
    "AVGO":  (200, 700),
    "CRDO":  ( 80, 350),
    "GEV":   (500, 1800),
    "BE":    (100, 500),
    "CAT":   (400, 1500),
    "VRT":   (150, 600),
    "RKLB":  ( 30, 180),
    "RTX":   ( 80, 300),
    "LMT":   (250, 800),
    "HWM":   (100, 450),
    "VRTX":  (200, 700),
    "MRNA":  ( 20, 120),
    "CRSP":  ( 20, 130),
}

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
}

