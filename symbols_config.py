"""
Central symbol configuration for the trading bot.

This is the single source of truth for:
- approved symbols
- price sanity ranges
- correlation clusters
- cluster exposure limits
- shared symbol lists used by research/parser/decision prompts
"""

SYMBOL_CONFIG = {
    # Core / original
    "AAPL":  {"price_range": (150, 500),  "clusters": ["mega_cap_tech"]},
    "SPY":   {"price_range": (400, 700),  "clusters": ["broad_index"]},
    "QQQ":   {"price_range": (400, 900),  "clusters": ["mega_cap_tech", "broad_index"]},
    "MSFT":  {"price_range": (200, 600),  "clusters": ["mega_cap_tech"]},
    "NVDA":  {"price_range": (80, 600),   "clusters": ["mega_cap_tech"]},
    "ORCL":  {"price_range": (80, 300),   "clusters": ["software_infra"]},
    "TSCO":  {"price_range": (20, 80),    "clusters": ["consumer"]},
    "TSLA":  {"price_range": (100, 800),  "clusters": ["consumer_growth"]},
    "META":  {"price_range": (200, 1000), "clusters": ["mega_cap_tech"]},
    "AMD":   {"price_range": (50, 600),   "clusters": ["mega_cap_tech"]},
    "CVX":   {"price_range": (100, 260),  "clusters": ["energy"]},
    "XOM":   {"price_range": (80, 215),   "clusters": ["energy"]},
    "GOOGL": {"price_range": (250, 550),  "clusters": ["mega_cap_tech"]},
    "GLD":   {"price_range": (250, 550),  "clusters": ["hedge"]},
    "IWM":   {"price_range": (180, 350),  "clusters": ["broad_index"]},

    # Existing expansion
    "AVGO":  {"price_range": (200, 700),  "clusters": ["mega_cap_tech", "ai_infra"]},
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
    "LLY":   {"price_range": (500, 1400), "clusters": ["healthcare"]},
    "LIN":   {"price_range": (300, 800),  "clusters": ["industrials"]},
    "GE":    {"price_range": (180, 500),  "clusters": ["industrials", "aerospace"]},

    # New additions — May 2026, batch 2
    "ASML":  {"price_range": (900, 2200), "clusters": ["mega_cap_tech", "ai_infra"]},
    "NFLX":  {"price_range": (50, 150),   "clusters": ["consumer_growth"]},
    "CRM":   {"price_range": (120, 300),  "clusters": ["software_infra"]},
    "COST":  {"price_range": (700, 1300), "clusters": ["consumer"]},
    "KO":    {"price_range": (55, 100),   "clusters": ["consumer"]},
    "ABBV":  {"price_range": (150, 275),  "clusters": ["healthcare"]},
    "MRK":   {"price_range": (80, 160),   "clusters": ["healthcare"]},
    "UNH":   {"price_range": (250, 600),  "clusters": ["healthcare"]},
}

APPROVED_SYMBOLS_LIST = list(SYMBOL_CONFIG.keys())
APPROVED_SYMBOLS = set(APPROVED_SYMBOLS_LIST)
APPROVED_SYMBOLS_CSV = ", ".join(APPROVED_SYMBOLS_LIST)

PRICE_RANGES = {
    symbol: cfg["price_range"]
    for symbol, cfg in SYMBOL_CONFIG.items()
}

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
    "consumer": 8.0,
    "consumer_growth": 8.0,
    "hedge": 8.0,
}
