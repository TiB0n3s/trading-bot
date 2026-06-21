"""Auto-sell / position momentum monitor configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass

from config._env import env_bool, env_float, env_int


def _paper_runtime_default(paper_value: str, live_value: str) -> str:
    mode = os.getenv("EXECUTION_MODE", "paper").strip().lower()
    return paper_value if mode in {"paper", "dry_run"} else live_value


@dataclass(frozen=True)
class AutoSellConfig:
    cooldown_minutes: int = 30
    min_hold_minutes_before_auto_sell: int = 15
    auto_sell: bool = False
    sell_candidates_only: bool = True
    use_sell_pressure: bool = False
    layered_ml_enabled: bool = True
    layered_ml_min_exit_confidence: float = 70.0
    layered_ml_strong_exit_confidence: float = 78.0
    layered_ml_max_loss_pct: float = -0.75
    layered_ml_min_sell_pressure: float = 5.0
    layered_ml_low_confidence: float = 45.0
    emergency_loss_pct: float = -1.25
    failed_high_run_session_pct: float = 4.0
    failed_high_run_loss_pct: float = -0.60
    failed_high_run_score: float = -4.0
    failed_high_run_15m_pct: float = -0.50
    failed_high_run_30m_pct: float = -0.50
    trailing_profit_min_pct: float = 0.75
    trailing_giveback_pct: float = 0.50
    trailing_current_floor_pct: float = -0.25
    hard_negative_loss_floor_pct: float = -0.50
    profit_tier_1_pct: float = 0.75
    profit_tier_1_score: float = -4.0
    profit_tier_2_pct: float = 1.50
    profit_tier_2_score: float = -2.0
    profit_tier_3_pct: float = 3.00
    sell_pressure_full_score: float = 12.0
    sell_pressure_max_loss_pct: float = -0.75
    min_profit_sell_pct: float = 0.50
    max_loss_sell_pct: float = -1.00
    hard_exit_max_loss_pct: float = -1.00
    hard_exit_score: float = -6.0
    severe_breakdown_loss_pct: float = -0.75
    severe_breakdown_score: float = -5.0
    severe_breakdown_15m_pct: float = -0.50
    severe_breakdown_30m_pct: float = -1.00
    severe_breakdown_vwap_pct: float = -0.75


def load_auto_sell_config(**overrides) -> AutoSellConfig:
    kwargs: dict = dict(
        cooldown_minutes=env_int("AUTO_SELL_COOLDOWN_MINUTES", 30),
        min_hold_minutes_before_auto_sell=env_int("MIN_HOLD_MINUTES_BEFORE_AUTO_SELL", 15),
        auto_sell=env_bool("POSITION_MOMENTUM_AUTO_SELL", False),
        sell_candidates_only=env_bool("POSITION_MOMENTUM_SELL_CANDIDATES_ONLY", True),
        use_sell_pressure=env_bool("POSITION_MOMENTUM_USE_SELL_PRESSURE", False),
        layered_ml_enabled=env_bool(
            "POSITION_MOMENTUM_LAYERED_ML_ENABLED",
            _paper_runtime_default("true", "false").lower() == "true",
        ),
        layered_ml_min_exit_confidence=env_float(
            "POSITION_MOMENTUM_LAYERED_ML_MIN_EXIT_CONFIDENCE", 70.0
        ),
        layered_ml_strong_exit_confidence=env_float(
            "POSITION_MOMENTUM_LAYERED_ML_STRONG_EXIT_CONFIDENCE", 78.0
        ),
        layered_ml_max_loss_pct=env_float("POSITION_MOMENTUM_LAYERED_ML_MAX_LOSS_PCT", -0.75),
        layered_ml_min_sell_pressure=env_float(
            "POSITION_MOMENTUM_LAYERED_ML_MIN_SELL_PRESSURE", 5.0
        ),
        layered_ml_low_confidence=env_float("POSITION_MOMENTUM_LAYERED_ML_LOW_CONFIDENCE", 45.0),
        emergency_loss_pct=env_float("POSITION_MOMENTUM_EMERGENCY_LOSS_PCT", -1.25),
        failed_high_run_session_pct=env_float("POSITION_MOMENTUM_FAILED_HIGH_RUN_SESSION_PCT", 4.0),
        failed_high_run_loss_pct=env_float("POSITION_MOMENTUM_FAILED_HIGH_RUN_LOSS_PCT", -0.60),
        failed_high_run_score=env_float("POSITION_MOMENTUM_FAILED_HIGH_RUN_SCORE", -4.0),
        failed_high_run_15m_pct=env_float("POSITION_MOMENTUM_FAILED_HIGH_RUN_15M_PCT", -0.50),
        failed_high_run_30m_pct=env_float("POSITION_MOMENTUM_FAILED_HIGH_RUN_30M_PCT", -0.50),
        trailing_profit_min_pct=env_float("POSITION_MOMENTUM_TRAILING_PROFIT_MIN_PCT", 0.75),
        trailing_giveback_pct=env_float("POSITION_MOMENTUM_TRAILING_GIVEBACK_PCT", 0.50),
        trailing_current_floor_pct=env_float("POSITION_MOMENTUM_TRAILING_CURRENT_FLOOR_PCT", -0.25),
        hard_negative_loss_floor_pct=env_float(
            "POSITION_MOMENTUM_HARD_NEGATIVE_LOSS_FLOOR_PCT", -0.50
        ),
        profit_tier_1_pct=env_float("POSITION_MOMENTUM_PROFIT_TIER_1_PCT", 0.75),
        profit_tier_1_score=env_float("POSITION_MOMENTUM_PROFIT_TIER_1_SCORE", -4.0),
        profit_tier_2_pct=env_float("POSITION_MOMENTUM_PROFIT_TIER_2_PCT", 1.50),
        profit_tier_2_score=env_float("POSITION_MOMENTUM_PROFIT_TIER_2_SCORE", -2.0),
        profit_tier_3_pct=env_float("POSITION_MOMENTUM_PROFIT_TIER_3_PCT", 3.00),
        sell_pressure_full_score=env_float("POSITION_MOMENTUM_SELL_PRESSURE_FULL_SCORE", 12.0),
        sell_pressure_max_loss_pct=env_float("POSITION_MOMENTUM_SELL_PRESSURE_MAX_LOSS_PCT", -0.75),
        min_profit_sell_pct=env_float("POSITION_MOMENTUM_MIN_PROFIT_SELL_PCT", 0.50),
        max_loss_sell_pct=env_float("POSITION_MOMENTUM_MAX_LOSS_SELL_PCT", -1.00),
        hard_exit_max_loss_pct=env_float("POSITION_MOMENTUM_HARD_EXIT_MAX_LOSS_PCT", -1.00),
        hard_exit_score=env_float("POSITION_MOMENTUM_HARD_EXIT_SCORE", -6.0),
        severe_breakdown_loss_pct=env_float("POSITION_MOMENTUM_SEVERE_BREAKDOWN_LOSS_PCT", -0.75),
        severe_breakdown_score=env_float("POSITION_MOMENTUM_SEVERE_BREAKDOWN_SCORE", -5.0),
        severe_breakdown_15m_pct=env_float("POSITION_MOMENTUM_SEVERE_BREAKDOWN_15M_PCT", -0.50),
        severe_breakdown_30m_pct=env_float("POSITION_MOMENTUM_SEVERE_BREAKDOWN_30M_PCT", -1.00),
        severe_breakdown_vwap_pct=env_float("POSITION_MOMENTUM_SEVERE_BREAKDOWN_VWAP_PCT", -0.75),
    )
    kwargs.update(overrides)
    return AutoSellConfig(**kwargs)
