"""
Typed configuration layer for the trading bot.

Each domain has a frozen dataclass and a factory function (``load_*_config``).
Callers construct a singleton at their own module level when they need one:

    from config.signal import load_signal_config
    signal_cfg = load_signal_config()

This keeps env-var capture at the callsite, not at import time, and lets tests
get a clean instance with ``load_signal_config(prediction_gate_mode="block")``
without touching any shared state.

Relationship to runtime_config.py:
  runtime_config.py owns execution-mode and broker-URL logic (EXECUTION_MODE,
  LIVE_TRADING_ENABLED, get_alpaca_base_url, cash-mode helpers).  This package
  owns everything else that was scattered across app.py, auto_buy_manager.py,
  and position_manager.py.

Adding a new env var:
  1. Add a field to the appropriate dataclass.
  2. Add the matching ``env_*`` call in the ``load_*`` factory.
  3. Remove the raw ``os.getenv`` call from the consuming module.
"""

from config.auto_buy import AutoBuyConfig, load_auto_buy_config
from config.conviction import ConvictionConfig, load_conviction_config
from config.ml import MLConfig, load_ml_config
from config.position_manager import PositionManagerConfig, load_position_manager_config
from config.risk import RiskConfig, load_risk_config
from config.signal import SignalConfig, load_signal_config

__all__ = [
    "SignalConfig",
    "load_signal_config",
    "RiskConfig",
    "load_risk_config",
    "AutoBuyConfig",
    "load_auto_buy_config",
    "ConvictionConfig",
    "load_conviction_config",
    "PositionManagerConfig",
    "load_position_manager_config",
    "MLConfig",
    "load_ml_config",
]
