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

SYMBOL_UNIVERSE_VERSION = "approved_universe_2026_06_11_ai_infra_dependencies_v1"
CONTEXT_SYMBOL_UNIVERSE_VERSION = "context_only_universe_2026_06_11_ai_infra_dependencies_v1"

SPACEX_CATALYST_APPROVED_SYMBOLS_LIST = [
    "NOC",
    "LHX",
    "HON",
    "TDY",
]

SPACEX_CATALYST_CONTEXT_ONLY_SYMBOLS_LIST = [
    "SPCX",
    "IRDM",
    "ASTS",
    "GSAT",
    "RDW",
    "PL",
    "BKSY",
    "SPIR",
    "BA",
]

SPACEX_CATALYST_SYMBOLS_LIST = (
    SPACEX_CATALYST_APPROVED_SYMBOLS_LIST + SPACEX_CATALYST_CONTEXT_ONLY_SYMBOLS_LIST
)
SPACEX_CATALYST_APPROVED_SYMBOLS = set(SPACEX_CATALYST_APPROVED_SYMBOLS_LIST)
SPACEX_CATALYST_CONTEXT_ONLY_SYMBOLS = set(SPACEX_CATALYST_CONTEXT_ONLY_SYMBOLS_LIST)
SPACEX_CATALYST_SYMBOLS = set(SPACEX_CATALYST_SYMBOLS_LIST)

AI_INFRASTRUCTURE_APPROVED_SYMBOLS_LIST = [
    "NVDA",
    "AMD",
    "INTC",
    "AVGO",
    "CSCO",
    "JNPR",
    "MRVL",
    "ANET",
    "VRT",
    "ETN",
    "GEV",
    "CEG",
]

AI_INFRASTRUCTURE_CONTEXT_ONLY_SYMBOLS_LIST = [
    "IREN",
    "CIFR",
    "WULF",
    "CORZ",
    "NBIS",
    "CRWV",
    "OKLO",
    "SMR",
]

AI_INFRASTRUCTURE_SYMBOLS_LIST = (
    AI_INFRASTRUCTURE_APPROVED_SYMBOLS_LIST + AI_INFRASTRUCTURE_CONTEXT_ONLY_SYMBOLS_LIST
)
AI_INFRASTRUCTURE_APPROVED_SYMBOLS = set(AI_INFRASTRUCTURE_APPROVED_SYMBOLS_LIST)
AI_INFRASTRUCTURE_CONTEXT_ONLY_SYMBOLS = set(AI_INFRASTRUCTURE_CONTEXT_ONLY_SYMBOLS_LIST)
AI_INFRASTRUCTURE_SYMBOLS = set(AI_INFRASTRUCTURE_SYMBOLS_LIST)

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
    "NOC",
    "LHX",
    "HON",
    "TDY",
    "INTC",
    "CSCO",
    "JNPR",
    "MRVL",
    "ANET",
    "ETN",
    "CEG",
]

INTERNAL_BAR_ONLY_SYMBOLS = set(INTERNAL_BAR_ONLY_SYMBOLS_LIST)

SYMBOL_CONFIG = {
    # Core / original
    "AAPL": {"price_range": (150, 500), "clusters": ["mega_cap_tech"]},
    "SPY": {"price_range": (400, 700), "clusters": ["broad_index"]},
    "QQQ": {"price_range": (400, 900), "clusters": ["mega_cap_tech", "broad_index"]},
    "MSFT": {"price_range": (200, 600), "clusters": ["mega_cap_tech"]},
    "NVDA": {"price_range": (80, 600), "clusters": ["mega_cap_tech"], "volume_note": "iex_thin"},
    "ORCL": {"price_range": (80, 300), "clusters": ["software_infra"]},
    "TSCO": {"price_range": (20, 80), "clusters": ["consumer"]},
    "TSLA": {"price_range": (100, 800), "clusters": ["consumer_growth"], "volume_note": "iex_thin"},
    "META": {
        "price_range": (200, 1000),
        "clusters": ["mega_cap_tech"],
        "max_spread_pct": 1.0,
        "volume_note": "iex_thin",
    },
    "AMD": {"price_range": (50, 600), "clusters": ["mega_cap_tech"], "volume_note": "iex_thin"},
    "CVX": {"price_range": (100, 260), "clusters": ["energy"]},
    "XOM": {"price_range": (80, 215), "clusters": ["energy"]},
    "GOOGL": {"price_range": (250, 550), "clusters": ["mega_cap_tech"], "volume_note": "iex_thin"},
    "GLD": {"price_range": (250, 550), "clusters": ["hedge"]},
    "IWM": {"price_range": (180, 350), "clusters": ["broad_index"]},
    # Existing expansion
    "AVGO": {
        "price_range": (200, 700),
        "clusters": ["mega_cap_tech", "ai_infra"],
        "max_spread_pct": 1.0,
        "volume_note": "iex_thin",
    },
    "CRDO": {"price_range": (80, 350), "clusters": ["ai_infra"]},
    "GEV": {"price_range": (500, 1800), "clusters": ["industrials", "power_energy"]},
    "BE": {"price_range": (100, 500), "clusters": ["power_energy"]},
    "CAT": {"price_range": (400, 1500), "clusters": ["industrials"]},
    "VRT": {"price_range": (150, 600), "clusters": ["ai_infra", "power_energy"]},
    "RKLB": {"price_range": (30, 180), "clusters": ["defense"]},
    "RTX": {"price_range": (80, 300), "clusters": ["defense"]},
    "LMT": {"price_range": (250, 800), "clusters": ["defense"]},
    "HWM": {"price_range": (100, 450), "clusters": ["defense", "industrials"]},
    "VRTX": {"price_range": (200, 700), "clusters": ["healthcare"]},
    "MRNA": {"price_range": (20, 120), "clusters": ["healthcare"]},
    "CRSP": {"price_range": (20, 130), "clusters": ["healthcare"]},
    "V": {"price_range": (200, 500), "clusters": ["payments"]},
    "MA": {"price_range": (350, 750), "clusters": ["payments"]},
    "LLY": {"price_range": (500, 1400), "clusters": ["healthcare"], "max_spread_pct": 1.5},
    "LIN": {"price_range": (300, 800), "clusters": ["industrials"]},
    "GE": {"price_range": (180, 500), "clusters": ["industrials", "aerospace"]},
    # New additions — May 2026, batch 2
    "ASML": {
        "price_range": (900, 2200),
        "clusters": ["mega_cap_tech", "ai_infra"],
        "max_spread_pct": 1.5,
    },
    "NFLX": {"price_range": (50, 150), "clusters": ["consumer_growth"]},
    "CRM": {"price_range": (120, 300), "clusters": ["software_infra"]},
    "COST": {"price_range": (700, 1300), "clusters": ["consumer"], "max_spread_pct": 1.5},
    "KO": {"price_range": (55, 100), "clusters": ["consumer"]},
    "ABBV": {"price_range": (150, 275), "clusters": ["healthcare"]},
    "MRK": {"price_range": (80, 160), "clusters": ["healthcare"]},
    "UNH": {"price_range": (250, 600), "clusters": ["healthcare"]},
    # Internal/bar-only research cohort — May 2026.
    # These are collected through Alpaca-derived research/momentum/features
    # without adding TradingView alerts, so their signal quality can be
    # compared against the alert-driven universe.
    "AMZN": {
        "price_range": (150, 350),
        "clusters": ["mega_cap_tech", "consumer_growth"],
        "volume_note": "iex_thin",
    },
    "JPM": {"price_range": (150, 400), "clusters": ["financials"]},
    "TSM": {"price_range": (100, 400), "clusters": ["mega_cap_tech", "semiconductors", "ai_infra"]},
    "SNPS": {"price_range": (300, 800), "clusters": ["software_infra", "semiconductors"]},
    "DELL": {"price_range": (60, 250), "clusters": ["hardware_infra", "ai_infra"]},
    "ADSK": {"price_range": (150, 450), "clusters": ["software_infra"]},
    "NTAP": {"price_range": (60, 200), "clusters": ["hardware_infra"]},
    "ZS": {"price_range": (100, 400), "clusters": ["software_infra", "cybersecurity"]},
    "PYPL": {"price_range": (30, 150), "clusters": ["payments"]},
    "SOFI": {"price_range": (5, 40), "clusters": ["financials", "consumer_growth"]},
    "PFE": {"price_range": (15, 70), "clusters": ["healthcare"]},
    "VZ": {"price_range": (25, 70), "clusters": ["telecom", "defensive"]},
    "T": {"price_range": (15, 45), "clusters": ["telecom", "defensive"]},
    "CMCSA": {"price_range": (20, 80), "clusters": ["telecom", "consumer"]},
    "DKS": {"price_range": (100, 350), "clusters": ["consumer"]},
    "MDB": {"price_range": (100, 600), "clusters": ["software_infra"]},
    "OKTA": {"price_range": (50, 220), "clusters": ["software_infra", "cybersecurity"]},
    "BURL": {"price_range": (150, 450), "clusters": ["consumer"]},
    # SpaceX-adjacent catalyst cohort — June 2026.
    # These are the initial liquid, higher-quality names approved for internal
    # bar/paper learning. Smaller space names remain context-only below until
    # liquidity and slippage evidence is sufficient for review.
    "NOC": {
        "price_range": (350, 900),
        "clusters": ["defense", "aerospace", "spacex_catalyst"],
        "max_spread_pct": 1.25,
    },
    "LHX": {
        "price_range": (150, 450),
        "clusters": ["defense", "aerospace", "spacex_catalyst"],
        "max_spread_pct": 1.25,
    },
    "HON": {
        "price_range": (120, 350),
        "clusters": ["industrials", "aerospace", "spacex_catalyst"],
        "max_spread_pct": 1.0,
    },
    "TDY": {
        "price_range": (250, 900),
        "clusters": ["industrials", "aerospace", "spacex_catalyst"],
        "max_spread_pct": 1.5,
    },
    # AI infrastructure dependency cohort — June 2026.
    # Approved here means internal-bar/paper-learning eligible. It does not
    # bypass normal signal, execution-quality, affordability, slippage, or risk
    # gates. More speculative compute/power names stay context-only below.
    "INTC": {
        "price_range": (10, 80),
        "clusters": ["semiconductors", "ai_infra"],
        "volume_note": "iex_thin",
    },
    "CSCO": {
        "price_range": (40, 120),
        "clusters": ["networking", "ai_infra", "hardware_infra"],
    },
    "JNPR": {
        "price_range": (25, 80),
        "clusters": ["networking", "ai_infra", "hardware_infra"],
    },
    "MRVL": {
        "price_range": (40, 180),
        "clusters": ["semiconductors", "networking", "ai_infra"],
        "volume_note": "iex_thin",
    },
    "ANET": {
        "price_range": (60, 200),
        "clusters": ["networking", "ai_infra", "hardware_infra"],
    },
    "ETN": {
        "price_range": (200, 600),
        "clusters": ["power_energy", "industrials", "ai_infra"],
    },
    "CEG": {
        "price_range": (150, 500),
        "clusters": ["power_energy", "utilities", "ai_infra"],
    },
}

APPROVED_SYMBOLS_LIST = list(SYMBOL_CONFIG.keys())
APPROVED_SYMBOLS = set(APPROVED_SYMBOLS_LIST)
APPROVED_SYMBOLS_CSV = ", ".join(APPROVED_SYMBOLS_LIST)

# Non-traded symbols used only to enrich context for approved symbols. These
# symbols must never become trade candidates unless explicitly moved into
# SYMBOL_CONFIG and approved by normal risk/ops review.
CONTEXT_ONLY_SYMBOL_CONFIG = {
    # Semiconductor / AI infrastructure suppliers and peers
    "MU": {
        "name": "Micron Technology",
        "relationship_type": "semiconductor_peer",
        "linked_symbols": ["NVDA", "AMD", "AVGO", "TSM", "ASML"],
        "themes": ["semiconductors", "ai_infra", "memory"],
    },
    "KLAC": {
        "name": "KLA",
        "relationship_type": "semiconductor_equipment_peer",
        "linked_symbols": ["ASML", "TSM", "NVDA", "AMD"],
        "themes": ["semiconductors", "equipment"],
    },
    "AMAT": {
        "name": "Applied Materials",
        "relationship_type": "semiconductor_equipment_peer",
        "linked_symbols": ["ASML", "TSM", "NVDA", "AMD"],
        "themes": ["semiconductors", "equipment"],
    },
    "LRCX": {
        "name": "Lam Research",
        "relationship_type": "semiconductor_equipment_peer",
        "linked_symbols": ["ASML", "TSM", "NVDA", "AMD"],
        "themes": ["semiconductors", "equipment"],
    },
    "SMCI": {
        "name": "Super Micro Computer",
        "relationship_type": "ai_hardware_peer",
        "linked_symbols": ["NVDA", "AMD", "DELL", "VRT"],
        "themes": ["ai_infra", "hardware_infra"],
    },
    "ARM": {
        "name": "Arm Holdings",
        "relationship_type": "semiconductor_ip_peer",
        "linked_symbols": ["NVDA", "AMD", "TSM", "AAPL"],
        "themes": ["semiconductors", "mobile", "ai_infra"],
    },
    # Cloud, enterprise software, and data-center demand context
    "NOW": {
        "name": "ServiceNow",
        "relationship_type": "software_peer",
        "linked_symbols": ["CRM", "ORCL", "MSFT", "SNPS"],
        "themes": ["software_infra", "enterprise_software"],
    },
    "PANW": {
        "name": "Palo Alto Networks",
        "relationship_type": "cybersecurity_peer",
        "linked_symbols": ["ZS", "OKTA", "MSFT"],
        "themes": ["cybersecurity", "software_infra"],
    },
    "CRWD": {
        "name": "CrowdStrike",
        "relationship_type": "cybersecurity_peer",
        "linked_symbols": ["ZS", "OKTA", "MSFT"],
        "themes": ["cybersecurity", "software_infra"],
    },
    # Consumer / retail peers
    "WMT": {
        "name": "Walmart",
        "relationship_type": "consumer_retail_peer",
        "linked_symbols": ["COST", "TSCO", "BURL", "DKS"],
        "themes": ["consumer", "retail"],
    },
    "TGT": {
        "name": "Target",
        "relationship_type": "consumer_retail_peer",
        "linked_symbols": ["COST", "BURL", "DKS", "TSCO"],
        "themes": ["consumer", "retail"],
    },
    # Healthcare / pharma context
    "NVO": {
        "name": "Novo Nordisk",
        "relationship_type": "pharma_peer",
        "linked_symbols": ["LLY", "PFE", "MRK", "ABBV"],
        "themes": ["healthcare", "glp1"],
    },
    "REGN": {
        "name": "Regeneron",
        "relationship_type": "biotech_peer",
        "linked_symbols": ["VRTX", "MRNA", "CRSP", "LLY"],
        "themes": ["healthcare", "biotech"],
    },
    # SpaceX catalyst context. These symbols enrich approved aerospace/defense
    # names but do not become trade candidates from event context alone.
    "SPCX": {
        "name": "SpaceX potential public ticker placeholder",
        "relationship_type": "spacex_primary_catalyst_placeholder",
        "linked_symbols": ["NOC", "LHX", "HON", "TDY", "RKLB", "LMT", "RTX", "HWM"],
        "themes": ["space", "ipo_watch", "aerospace", "defense"],
        "authority_note": "context_only_until_public_listing_and_operator_review",
    },
    "IRDM": {
        "name": "Iridium Communications",
        "relationship_type": "space_communications_peer",
        "linked_symbols": ["NOC", "LHX", "HON", "TDY", "RKLB"],
        "themes": ["space", "satellite_communications", "aerospace"],
        "authority_note": "context_only_until_liquidity_and_slippage_review",
    },
    "ASTS": {
        "name": "AST SpaceMobile",
        "relationship_type": "space_communications_peer",
        "linked_symbols": ["NOC", "LHX", "HON", "TDY", "RKLB"],
        "themes": ["space", "satellite_communications", "speculative_space"],
        "authority_note": "context_only_until_liquidity_and_slippage_review",
    },
    "GSAT": {
        "name": "Globalstar",
        "relationship_type": "space_communications_peer",
        "linked_symbols": ["NOC", "LHX", "HON", "TDY", "RKLB"],
        "themes": ["space", "satellite_communications", "speculative_space"],
        "authority_note": "context_only_until_liquidity_and_slippage_review",
    },
    "RDW": {
        "name": "Redwire",
        "relationship_type": "space_infrastructure_peer",
        "linked_symbols": ["NOC", "LHX", "HON", "TDY", "RKLB"],
        "themes": ["space", "space_infrastructure", "speculative_space"],
        "authority_note": "context_only_until_liquidity_and_slippage_review",
    },
    "PL": {
        "name": "Planet Labs",
        "relationship_type": "space_data_peer",
        "linked_symbols": ["NOC", "LHX", "HON", "TDY", "RKLB"],
        "themes": ["space", "earth_observation", "space_data"],
        "authority_note": "context_only_until_liquidity_and_slippage_review",
    },
    "BKSY": {
        "name": "BlackSky Technology",
        "relationship_type": "space_data_peer",
        "linked_symbols": ["NOC", "LHX", "HON", "TDY", "RKLB"],
        "themes": ["space", "earth_observation", "space_data", "speculative_space"],
        "authority_note": "context_only_until_liquidity_and_slippage_review",
    },
    "SPIR": {
        "name": "Spire Global",
        "relationship_type": "space_data_peer",
        "linked_symbols": ["NOC", "LHX", "HON", "TDY", "RKLB"],
        "themes": ["space", "space_data", "satellite_communications", "speculative_space"],
        "authority_note": "context_only_until_liquidity_and_slippage_review",
    },
    "BA": {
        "name": "Boeing",
        "relationship_type": "aerospace_prime_peer",
        "linked_symbols": ["NOC", "LHX", "HON", "TDY", "GE", "HWM", "LMT", "RTX"],
        "themes": ["aerospace", "defense", "space"],
        "authority_note": "context_only_for_spacex_catalyst_until_explicit_promotion_review",
    },
    # AI infrastructure dependency context. These symbols are collected only as
    # spillover/context until liquidity, spread, slippage, and realized learning
    # support explicit promotion into SYMBOL_CONFIG.
    "IREN": {
        "name": "IREN Limited",
        "relationship_type": "ai_compute_power_peer",
        "linked_symbols": ["NVDA", "AMD", "AVGO", "VRT", "ETN", "CEG"],
        "themes": ["ai_infra", "data_center", "bitcoin_miner_to_ai_compute", "power_energy"],
        "authority_note": "context_only_until_liquidity_slippage_and_ai_compute_revenue_review",
    },
    "CIFR": {
        "name": "Cipher Digital",
        "relationship_type": "ai_hpc_data_center_peer",
        "linked_symbols": ["NVDA", "AMD", "AVGO", "VRT", "ETN", "CEG"],
        "themes": ["ai_infra", "hpc", "data_center", "power_energy"],
        "authority_note": "context_only_normalized_from_user_cif_until_promotion_review",
    },
    "WULF": {
        "name": "TeraWulf",
        "relationship_type": "ai_compute_power_peer",
        "linked_symbols": ["NVDA", "AMD", "AVGO", "VRT", "ETN", "CEG"],
        "themes": ["ai_infra", "data_center", "bitcoin_miner_to_ai_compute", "power_energy"],
        "authority_note": "context_only_until_liquidity_slippage_and_ai_compute_revenue_review",
    },
    "CORZ": {
        "name": "Core Scientific",
        "relationship_type": "ai_hpc_data_center_peer",
        "linked_symbols": ["NVDA", "AMD", "AVGO", "VRT", "ETN", "CEG"],
        "themes": ["ai_infra", "hpc", "data_center", "power_energy"],
        "authority_note": "context_only_until_liquidity_slippage_and_contract_quality_review",
    },
    "NBIS": {
        "name": "Nebius Group",
        "relationship_type": "ai_cloud_provider_peer",
        "linked_symbols": ["NVDA", "AMD", "AVGO", "ORCL", "MSFT"],
        "themes": ["ai_infra", "ai_cloud", "gpu_compute"],
        "authority_note": "context_only_normalized_from_user_nabis_until_promotion_review",
    },
    "CRWV": {
        "name": "CoreWeave",
        "relationship_type": "ai_cloud_provider_peer",
        "linked_symbols": ["NVDA", "AMD", "AVGO", "ORCL", "MSFT", "VRT"],
        "themes": ["ai_infra", "ai_cloud", "gpu_compute", "data_center"],
        "authority_note": "context_only_normalized_from_user_crw_until_promotion_review",
    },
    "OKLO": {
        "name": "Oklo",
        "relationship_type": "advanced_nuclear_power_peer",
        "linked_symbols": ["CEG", "ETN", "VRT", "GEV"],
        "themes": ["ai_infra", "power_energy", "advanced_nuclear", "speculative_power"],
        "authority_note": "context_only_until_revenue_liquidity_and_regulatory_review",
    },
    "SMR": {
        "name": "NuScale Power",
        "relationship_type": "advanced_nuclear_power_peer",
        "linked_symbols": ["CEG", "ETN", "VRT", "GEV"],
        "themes": ["ai_infra", "power_energy", "advanced_nuclear", "speculative_power"],
        "authority_note": "context_only_until_revenue_liquidity_and_regulatory_review",
    },
}

CONTEXT_ONLY_SYMBOLS_LIST = list(CONTEXT_ONLY_SYMBOL_CONFIG.keys())
CONTEXT_ONLY_SYMBOLS = set(CONTEXT_ONLY_SYMBOLS_LIST)
EVENT_CONTEXT_SYMBOLS_LIST = APPROVED_SYMBOLS_LIST + CONTEXT_ONLY_SYMBOLS_LIST
EVENT_CONTEXT_SYMBOLS = set(EVENT_CONTEXT_SYMBOLS_LIST)
TRADINGVIEW_ALERT_SYMBOLS_LIST = [
    symbol for symbol in APPROVED_SYMBOLS_LIST if symbol not in INTERNAL_BAR_ONLY_SYMBOLS
]
TRADINGVIEW_ALERT_SYMBOLS = set(TRADINGVIEW_ALERT_SYMBOLS_LIST)

SYMBOL_SIGNAL_SOURCE = {
    symbol: "internal_bar_only" if symbol in INTERNAL_BAR_ONLY_SYMBOLS else "tradingview_alert"
    for symbol in APPROVED_SYMBOLS_LIST
}

PRICE_RANGES = {symbol: cfg["price_range"] for symbol, cfg in SYMBOL_CONFIG.items()}

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
    symbol: cfg["volume_note"] for symbol, cfg in SYMBOL_CONFIG.items() if "volume_note" in cfg
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
    "networking": 10.0,
    "financials": 8.0,
    "telecom": 8.0,
    "defensive": 8.0,
    "cybersecurity": 8.0,
    "consumer": 8.0,
    "consumer_growth": 8.0,
    "hedge": 8.0,
    "utilities": 8.0,
}
