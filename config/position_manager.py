"""Position manager exit/protection configuration."""

from __future__ import annotations

from dataclasses import dataclass

from config._env import _check, env_bool, env_float


@dataclass(frozen=True)
class PositionManagerConfig:
    # Execution
    live_sells: bool = False
    partial_sell_pct: float = 0.50
    promote_unexecutable_partials: bool = True
    min_profit_partial_pct: float = 0.75
    profit_giveback_trigger_pct: float = 50.0

    # Breakeven lock
    breakeven_lock_trigger_pct: float = 0.50
    breakeven_lock_floor_pct: float = 0.05
    weak_setup_breakeven_lock_trigger_pct: float = 0.35
    weak_setup_breakeven_lock_floor_pct: float = 0.02

    # Hard exits
    full_exit_loss_pct: float = -1.25
    vwap_loss_exit_pct: float = -0.35

    # Continuation check
    continuation_exit_check_enabled: bool = True
    continuation_hard_loss_floor_pct: float = -0.75
    continuation_min_momentum_pct: float = 0.05
    continuation_min_vwap_dist_pct: float = 0.05

    # Session-context momentum gate
    position_momentum_session_context_enabled: bool = True
    position_momentum_retained_strength_enabled: bool = True

    # Strong momentum thresholds
    momentum_strong_score_min: float = 6.0
    momentum_strong_return_min_pct: float = 1.0
    momentum_strong_minutes_min: float = 20.0

    # Retained momentum thresholds
    momentum_retained_min_score: float = 3.0
    momentum_retained_min_return_pct: float = 0.25
    momentum_retained_min_vwap_dist_pct: float = -0.25

    # Momentum break thresholds
    momentum_break_pullback_pct: float = -0.75
    momentum_break_vwap_dist_pct: float = -0.35
    momentum_break_15m_pct: float = -0.35
    momentum_break_30m_pct: float = -0.50

    # Profit capture tiers
    profit_capture_enabled: bool = True
    tier2_peak_pct: float = 1.50
    tier3_peak_pct: float = 3.00
    retained_tier2_giveback_pct: float = 60.0
    retained_tier3_giveback_pct: float = 45.0
    retained_min_profit_to_protect_pct: float = 0.40

    # High-gain lock tiers
    high_gain_lock_enabled: bool = True
    lock_tier1_peak_pct: float = 1.00
    lock_tier1_floor_pct: float = 0.30
    lock_tier2_peak_pct: float = 1.50
    lock_tier2_floor_pct: float = 0.60
    lock_tier3_peak_pct: float = 2.50
    lock_tier3_floor_pct: float = 1.00
    lock_tier4_peak_pct: float = 4.00
    lock_tier4_floor_pct: float = 1.75

    def __post_init__(self) -> None:
        _check(
            0 < self.partial_sell_pct <= 1.0,
            "partial_sell_pct", "POSITION_MANAGER_PARTIAL_SELL_PCT",
            self.partial_sell_pct, "must be in (0, 1]",
        )
        _check(
            self.min_profit_partial_pct >= 0,
            "min_profit_partial_pct", "POSITION_MANAGER_MIN_PROFIT_PARTIAL_PCT",
            self.min_profit_partial_pct, "must be >= 0",
        )
        _check(
            self.profit_giveback_trigger_pct >= 0,
            "profit_giveback_trigger_pct", "POSITION_MANAGER_PROFIT_GIVEBACK_TRIGGER_PCT",
            self.profit_giveback_trigger_pct, "must be >= 0",
        )
        _check(
            self.breakeven_lock_trigger_pct >= 0,
            "breakeven_lock_trigger_pct", "BREAKEVEN_LOCK_TRIGGER_PCT",
            self.breakeven_lock_trigger_pct, "must be >= 0",
        )
        _check(
            self.breakeven_lock_floor_pct >= 0,
            "breakeven_lock_floor_pct", "BREAKEVEN_LOCK_FLOOR_PCT",
            self.breakeven_lock_floor_pct, "must be >= 0",
        )
        _check(
            self.full_exit_loss_pct <= 0,
            "full_exit_loss_pct", "POSITION_MANAGER_FULL_EXIT_LOSS_PCT",
            self.full_exit_loss_pct, "must be <= 0",
        )
        _check(
            self.vwap_loss_exit_pct <= 0,
            "vwap_loss_exit_pct", "POSITION_MANAGER_VWAP_LOSS_EXIT_PCT",
            self.vwap_loss_exit_pct, "must be <= 0",
        )
        _check(
            self.continuation_hard_loss_floor_pct <= 0,
            "continuation_hard_loss_floor_pct",
            "POSITION_MANAGER_CONTINUATION_HARD_LOSS_FLOOR_PCT",
            self.continuation_hard_loss_floor_pct, "must be <= 0",
        )
        _check(
            self.tier2_peak_pct > 0,
            "tier2_peak_pct", "POSITION_MANAGER_TIER2_PEAK_PCT",
            self.tier2_peak_pct, "must be > 0",
        )
        _check(
            self.tier3_peak_pct > self.tier2_peak_pct,
            "tier3_peak_pct", "POSITION_MANAGER_TIER3_PEAK_PCT",
            self.tier3_peak_pct,
            f"must be > tier2_peak_pct ({self.tier2_peak_pct})",
        )
        _check(
            self.retained_tier2_giveback_pct >= 0,
            "retained_tier2_giveback_pct", "POSITION_MANAGER_RETAINED_TIER2_GIVEBACK_PCT",
            self.retained_tier2_giveback_pct, "must be >= 0",
        )
        _check(
            self.retained_tier3_giveback_pct >= 0,
            "retained_tier3_giveback_pct", "POSITION_MANAGER_RETAINED_TIER3_GIVEBACK_PCT",
            self.retained_tier3_giveback_pct, "must be >= 0",
        )
        _check(
            self.lock_tier1_floor_pct < self.lock_tier1_peak_pct,
            "lock_tier1_floor_pct", "POSITION_MANAGER_LOCK_TIER1_FLOOR_PCT",
            self.lock_tier1_floor_pct,
            f"must be < lock_tier1_peak_pct ({self.lock_tier1_peak_pct})",
        )
        _check(
            self.lock_tier2_floor_pct < self.lock_tier2_peak_pct,
            "lock_tier2_floor_pct", "POSITION_MANAGER_LOCK_TIER2_FLOOR_PCT",
            self.lock_tier2_floor_pct,
            f"must be < lock_tier2_peak_pct ({self.lock_tier2_peak_pct})",
        )
        _check(
            self.lock_tier3_floor_pct < self.lock_tier3_peak_pct,
            "lock_tier3_floor_pct", "POSITION_MANAGER_LOCK_TIER3_FLOOR_PCT",
            self.lock_tier3_floor_pct,
            f"must be < lock_tier3_peak_pct ({self.lock_tier3_peak_pct})",
        )
        _check(
            self.lock_tier4_floor_pct < self.lock_tier4_peak_pct,
            "lock_tier4_floor_pct", "POSITION_MANAGER_LOCK_TIER4_FLOOR_PCT",
            self.lock_tier4_floor_pct,
            f"must be < lock_tier4_peak_pct ({self.lock_tier4_peak_pct})",
        )


def load_position_manager_config(**overrides) -> PositionManagerConfig:
    """Construct PositionManagerConfig from current env, with optional kwarg overrides.

    Production code uses the ``position_manager_cfg`` singleton from ``config``.
    Tests call this factory directly after patching env (or pass overrides)
    to get a fresh instance without touching the singleton.

    Example::

        cfg = load_position_manager_config(live_sells=False)
    """
    kwargs: dict = dict(
        live_sells=env_bool("POSITION_MANAGER_LIVE_SELLS", False),
        partial_sell_pct=env_float("POSITION_MANAGER_PARTIAL_SELL_PCT", 0.50),
        promote_unexecutable_partials=env_bool("PROMOTE_UNEXECUTABLE_PARTIALS", True),
        min_profit_partial_pct=env_float("POSITION_MANAGER_MIN_PROFIT_PARTIAL_PCT", 0.75),
        profit_giveback_trigger_pct=env_float(
            "POSITION_MANAGER_PROFIT_GIVEBACK_TRIGGER_PCT", 50.0
        ),
        breakeven_lock_trigger_pct=env_float("BREAKEVEN_LOCK_TRIGGER_PCT", 0.50),
        breakeven_lock_floor_pct=env_float("BREAKEVEN_LOCK_FLOOR_PCT", 0.05),
        weak_setup_breakeven_lock_trigger_pct=env_float(
            "WEAK_SETUP_BREAKEVEN_LOCK_TRIGGER_PCT", 0.35
        ),
        weak_setup_breakeven_lock_floor_pct=env_float(
            "WEAK_SETUP_BREAKEVEN_LOCK_FLOOR_PCT", 0.02
        ),
        full_exit_loss_pct=env_float("POSITION_MANAGER_FULL_EXIT_LOSS_PCT", -1.25),
        vwap_loss_exit_pct=env_float("POSITION_MANAGER_VWAP_LOSS_EXIT_PCT", -0.35),
        continuation_exit_check_enabled=env_bool(
            "CONTINUATION_EXIT_CHECK_ENABLED", True
        ),
        continuation_hard_loss_floor_pct=env_float(
            "POSITION_MANAGER_CONTINUATION_HARD_LOSS_FLOOR_PCT", -0.75
        ),
        continuation_min_momentum_pct=env_float(
            "POSITION_MANAGER_CONTINUATION_MIN_MOMENTUM_PCT", 0.05
        ),
        continuation_min_vwap_dist_pct=env_float(
            "POSITION_MANAGER_CONTINUATION_MIN_VWAP_DIST_PCT", 0.05
        ),
        position_momentum_session_context_enabled=env_bool(
            "POSITION_MOMENTUM_SESSION_CONTEXT_ENABLED", True
        ),
        position_momentum_retained_strength_enabled=env_bool(
            "POSITION_MOMENTUM_RETAINED_STRENGTH_ENABLED", True
        ),
        momentum_strong_score_min=env_float("POSITION_MOMENTUM_STRONG_SCORE_MIN", 6.0),
        momentum_strong_return_min_pct=env_float(
            "POSITION_MOMENTUM_STRONG_RETURN_MIN_PCT", 1.0
        ),
        momentum_strong_minutes_min=env_float(
            "POSITION_MOMENTUM_STRONG_MINUTES_MIN", 20.0
        ),
        momentum_retained_min_score=env_float("POSITION_MOMENTUM_RETAINED_MIN_SCORE", 3.0),
        momentum_retained_min_return_pct=env_float(
            "POSITION_MOMENTUM_RETAINED_MIN_RETURN_PCT", 0.25
        ),
        momentum_retained_min_vwap_dist_pct=env_float(
            "POSITION_MOMENTUM_RETAINED_MIN_VWAP_DIST_PCT", -0.25
        ),
        momentum_break_pullback_pct=env_float("POSITION_MOMENTUM_BREAK_PULLBACK_PCT", -0.75),
        momentum_break_vwap_dist_pct=env_float(
            "POSITION_MOMENTUM_BREAK_VWAP_DIST_PCT", -0.35
        ),
        momentum_break_15m_pct=env_float("POSITION_MOMENTUM_BREAK_15M_PCT", -0.35),
        momentum_break_30m_pct=env_float("POSITION_MOMENTUM_BREAK_30M_PCT", -0.50),
        profit_capture_enabled=env_bool("POSITION_MANAGER_PROFIT_CAPTURE_ENABLED", True),
        tier2_peak_pct=env_float("POSITION_MANAGER_TIER2_PEAK_PCT", 1.50),
        tier3_peak_pct=env_float("POSITION_MANAGER_TIER3_PEAK_PCT", 3.00),
        retained_tier2_giveback_pct=env_float(
            "POSITION_MANAGER_RETAINED_TIER2_GIVEBACK_PCT", 60.0
        ),
        retained_tier3_giveback_pct=env_float(
            "POSITION_MANAGER_RETAINED_TIER3_GIVEBACK_PCT", 45.0
        ),
        retained_min_profit_to_protect_pct=env_float(
            "POSITION_MANAGER_RETAINED_MIN_PROFIT_TO_PROTECT_PCT", 0.40
        ),
        high_gain_lock_enabled=env_bool("POSITION_MANAGER_HIGH_GAIN_LOCK_ENABLED", True),
        lock_tier1_peak_pct=env_float("POSITION_MANAGER_LOCK_TIER1_PEAK_PCT", 1.00),
        lock_tier1_floor_pct=env_float("POSITION_MANAGER_LOCK_TIER1_FLOOR_PCT", 0.30),
        lock_tier2_peak_pct=env_float("POSITION_MANAGER_LOCK_TIER2_PEAK_PCT", 1.50),
        lock_tier2_floor_pct=env_float("POSITION_MANAGER_LOCK_TIER2_FLOOR_PCT", 0.60),
        lock_tier3_peak_pct=env_float("POSITION_MANAGER_LOCK_TIER3_PEAK_PCT", 2.50),
        lock_tier3_floor_pct=env_float("POSITION_MANAGER_LOCK_TIER3_FLOOR_PCT", 1.00),
        lock_tier4_peak_pct=env_float("POSITION_MANAGER_LOCK_TIER4_PEAK_PCT", 4.00),
        lock_tier4_floor_pct=env_float("POSITION_MANAGER_LOCK_TIER4_FLOOR_PCT", 1.75),
    )
    kwargs.update(overrides)
    return PositionManagerConfig(**kwargs)
