"""Compatibility wrapper for position manager configuration."""

from config.position_manager import PositionManagerConfig, load_position_manager_config

PositionsConfig = PositionManagerConfig
load_positions_config = load_position_manager_config

__all__ = [
    "PositionManagerConfig",
    "PositionsConfig",
    "load_position_manager_config",
    "load_positions_config",
]
