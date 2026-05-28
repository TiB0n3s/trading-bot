"""
Central symbol configuration for the trading bot.

This is the single source of truth for:
- approved symbols
- price sanity ranges
- correlation clusters
- cluster exposure limits
- signal-source cohorts for TradingView vs. internal/bar-only research
- shared symbol lists used by research/parser/decision prompts
"""

SYMBOL_UNIVERSE_VERSION = "approved_universe_2026_05_26_internal_bar_expansion_v1"

INTERNAL_BAR_ONLY_SYMBOLS_LIST = [
    "AMZN",
    "JPM",
    "TSM",
    "SNPS",
    "DELL",
    "ADSK",
    "NTAP",
    "ZS",
    "PYPL",
    "SOFI",
    "PFE",
    "VZ",
    "T",
    "CMCSA",
    "DKS",
    "MDB",
    "OKTA",
    "BURL",
    "ASML",  # $1600+ share price; affordability gate always blocks at current account size
]

INTERNAL_BAR_ONLY_SYMBOLS = set(INTERNAL_BAR_ONLY_SYMBOLS_LIST)

SYMBOL_CONFIG = {
    # Core / original
    "AAPL":  {"price_range": (150, 500),  "clusters": ["mega_cap_tech"]},
    "SPY":   {"price_range": (400, 700),  "clusters": ["broad_index"]},
    "QQQ":   {"price_range": (400, 900),  "clusters": ["mega_cap_tech", "broad_index"]},
    "MSFT":  {"price_range": (200, 600),  "clusters": ["mega_cap_tech"]},
    "NVDA":  {"price_range": (80, 600),   "clusters": ["mega_cap_tech"], "volume_note": "iex_thin"},
    "ORCL":  {"price_range": (80, 300),   "clusters": ["software_infra"]},
    "TSCO":  {"price_range": (20, 80),    "clusters": ["consumer"]},
    "TSLA":  {"price_range": (100, 800),  "clusters": ["consumer_growth"], "volume_note": "iex_thin"},
    "META":  {"price_range": (200, 1000), "clusters": ["mega_cap_tech"], "max_spread_pct": 1.0, "volume_note": "iex_thin"},
    "AMD":   {"price_range": (50, 600),   "clusters": ["mega_cap_tech"], "volume_note": "iex_thin"},
    "CVX":   {"price_range": (100, 260),  "clusters": ["energy"]},
    "XOM":   {"price_range": (80, 215),   "clusters": ["energy"]},
    "GOOGL": {"price_range": (250, 550),  "clusters": ["mega_cap_tech"], "volume_note": "iex_thin"},
    "GLD":   {"price_range": (250, 550),  "clusters": ["hedge"]},
    "IWM":   {"price_range": (180, 350),  "clusters": ["broad_index"]},

    # Existing expansion
    "AVGO":  {"price_range": (200, 700),  "clusters": ["mega_cap_tech", "ai_infra"], "max_spread_pct": 1.0, "volume_note": "iex_thin"},
    "CRDO":  {"price_range": (80, 350),   "clusters": ["ai_infra"]},
    "GEV":   {"price_range": (500, 1800), "clusters": ["industrials", "power_energy"]},
    "BE":    {"price_range": (100, 500),  "clusters": ["power_energy"]},
    "CAT":   {"price_range": (400, 1500), "clusters": ["industrials"]},
    "VRT":   {"price_range": (150, 600),  "clusters": ["ai_infra", "power_energy"]},
    "RKLB":  {"price_range": (30, 180),   "clusters": ["defense"]},
    "RTX":   {"price_range": (80, 300),   "clusters": ["defense"]},
    "LMT":   {"price_range": (250, 800),  "clusters": ["defense"]},
    "HWM":   {"price_range": (100, 450),  "clusters": ["defense", "industrials"]},
    "VRTX":  {"price_range": (200, 700),  "clusters": ["healthcare"]},
    "MRNA":  {"price_range": (20, 120),   "clusters": ["healthcare"]},
    "CRSP":  {"price_range": (20, 130),   "clusters": ["healthcare"]},

    "V":     {"price_range": (200, 500),  "clusters": ["payments"]},
    "MA":    {"price_range": (350, 750),  "clusters": ["payments"]},
    "LLY":   {"price_range": (500, 1400), "clusters": ["healthcare"], "max_spread_pct": 1.5},
    "LIN":   {"price_range": (300, 800),  "clusters": ["industrials"]},
    "GE":    {"price_range": (180, 500),  "clusters": ["industrials", "aerospace"]},

    # New additions — May 2026, batch 2
    "ASML":  {"price_range": (900, 2200), "clusters": ["mega_cap_tech", "ai_infra"], "max_spread_pct": 1.5},
    "NFLX":  {"price_range": (50, 150),   "clusters": ["consumer_growth"]},
    "CRM":   {"price_range": (120, 300),  "clusters": ["software_infra"]},
    "COST":  {"price_range": (700, 1300), "clusters": ["consumer"], "max_spread_pct": 1.5},
    "KO":    {"price_range": (55, 100),   "clusters": ["consumer"]},
    "ABBV":  {"price_range": (150, 275),  "clusters": ["healthcare"]},
    "MRK":   {"price_range": (80, 160),   "clusters": ["healthcare"]},
    "UNH":   {"price_range": (250, 600),  "clusters": ["healthcare"]},

    # Internal/bar-only research cohort — May 2026.
    # These are collected through Alpaca-derived research/momentum/features
    # without adding TradingView alerts, so their signal quality can be
    # compared against the alert-driven universe.
    "AMZN":  {"price_range": (150, 350),  "clusters": ["mega_cap_tech", "consumer_growth"], "volume_note": "iex_thin"},
    "JPM":   {"price_range": (150, 400),  "clusters": ["financials"]},
    "TSM":   {"price_range": (100, 400),  "clusters": ["mega_cap_tech", "semiconductors", "ai_infra"]},
    "SNPS":  {"price_range": (300, 800),  "clusters": ["software_infra", "semiconductors"]},
    "DELL":  {"price_range": (60, 250),   "clusters": ["hardware_infra", "ai_infra"]},
    "ADSK":  {"price_range": (150, 450),  "clusters": ["software_infra"]},
    "NTAP":  {"price_range": (60, 200),   "clusters": ["hardware_infra"]},
    "ZS":    {"price_range": (100, 400),  "clusters": ["software_infra", "cybersecurity"]},
    "PYPL":  {"price_range": (30, 150),   "clusters": ["payments"]},
    "SOFI":  {"price_range": (5, 40),     "clusters": ["financials", "consumer_growth"]},
    "PFE":   {"price_range": (15, 70),    "clusters": ["healthcare"]},
    "VZ":    {"price_range": (25, 70),    "clusters": ["telecom", "defensive"]},
    "T":     {"price_range": (15, 45),    "clusters": ["telecom", "defensive"]},
    "CMCSA": {"price_range": (20, 80),    "clusters": ["telecom", "consumer"]},
    "DKS":   {"price_range": (100, 350),  "clusters": ["consumer"]},
    "MDB":   {"price_range": (100, 600),  "clusters": ["software_infra"]},
    "OKTA":  {"price_range": (50, 220),   "clusters": ["software_infra", "cybersecurity"]},
    "BURL":  {"price_range": (150, 450),  "clusters": ["consumer"]},
}

APPROVED_SYMBOLS_LIST = list(SYMBOL_CONFIG.keys())
APPROVED_SYMBOLS = set(APPROVED_SYMBOLS_LIST)
APPROVED_SYMBOLS_CSV = ", ".join(APPROVED_SYMBOLS_LIST)
TRADINGVIEW_ALERT_SYMBOLS_LIST = [
    symbol for symbol in APPROVED_SYMBOLS_LIST
    if symbol not in INTERNAL_BAR_ONLY_SYMBOLS
]
TRADINGVIEW_ALERT_SYMBOLS = set(TRADINGVIEW_ALERT_SYMBOLS_LIST)

SYMBOL_SIGNAL_SOURCE = {
    symbol: "internal_bar_only" if symbol in INTERNAL_BAR_ONLY_SYMBOLS else "tradingview_alert"
    for symbol in APPROVED_SYMBOLS_LIST
}

PRICE_RANGES = {
    symbol: cfg["price_range"]
    for symbol, cfg in SYMBOL_CONFIG.items()
}

# Per-symbol bid/ask spread overrides for high-priced names whose natural
# tick-size spread exceeds the flat default threshold (MAX_BID_ASK_SPREAD_PCT).
# Absent here → falls back to the global default.
SYMBOL_MAX_SPREAD_PCT: dict[str, float] = {
    symbol: cfg["max_spread_pct"]
    for symbol, cfg in SYMBOL_CONFIG.items()
    if "max_spread_pct" in cfg
}

# Symbols where IEX-reported volume is known to be structurally unrepresentative
# of consolidated tape volume. IEX captures only a fraction of trades for high-
# volume names (NVDA, AMD, TSLA, META, etc.) because most volume routes through
# NYSE/NASDAQ/dark pools that IEX never sees. Volume-based gates (surge detection,
# fast-lane bypass) are therefore unreliable for these symbols on IEX data.
# Value "iex_thin" = IEX market share too low for surge thresholds to be trusted.
SYMBOL_VOLUME_NOTE: dict[str, str] = {
    symbol: cfg["volume_note"]
    for symbol, cfg in SYMBOL_CONFIG.items()
    if "volume_note" in cfg
}

IEX_THIN_SYMBOLS: frozenset[str] = frozenset(
    symbol for symbol, note in SYMBOL_VOLUME_NOTE.items() if note == "iex_thin"
)

CORRELATION_CLUSTERS = {}
for symbol, cfg in SYMBOL_CONFIG.items():
    for cluster in cfg.get("clusters", []):
        CORRELATION_CLUSTERS.setdefault(cluster, set()).add(symbol)

CLUSTER_EXPOSURE_LIMITS = {
    "mega_cap_tech": 15.0,
    "broad_index": 12.0,
    "energy": 8.0,
    "defense": 10.0,
    "healthcare": 10.0,
    "industrials": 12.0,
    "ai_infra": 12.0,
    "power_energy": 10.0,
    "payments": 8.0,
    "aerospace": 8.0,
    "software_infra": 8.0,
    "semiconductors": 10.0,
    "hardware_infra": 8.0,
    "financials": 8.0,
    "telecom": 8.0,
    "defensive": 8.0,
    "cybersecurity": 8.0,
    "consumer": 8.0,
    "consumer_growth": 8.0,
    "hedge": 8.0,
}
