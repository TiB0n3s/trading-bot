"""Position manager exit/protection configuration."""

from __future__ import annotations

from dataclasses import dataclass

from config._env import _check, env_bool, env_float, env_int


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

    # Bad-entry containment
    bad_entry_containment_enabled: bool = True
    bad_entry_containment_loss_pct: float = -0.65
    bad_entry_containment_max_peak_pct: float = 0.15

    # Peak-aware breakeven lock
    peak_lock_tier1_peak_pct: float = 0.30
    peak_lock_tier1_floor_pct: float = 0.10
    peak_lock_tier2_peak_pct: float = 0.60
    peak_lock_tier2_floor_pct: float = 0.30
    peak_lock_tier3_peak_pct: float = 1.00
    peak_lock_tier3_floor_pct: float = 0.45
    weak_peak_lock_tier1_peak_pct: float = 0.30
    weak_peak_lock_tier1_floor_pct: float = 0.15
    weak_peak_lock_tier2_peak_pct: float = 0.50
    weak_peak_lock_tier2_floor_pct: float = 0.35

    # Quality-split exit thresholds
    strong_conviction_profit_giveback_trigger_pct: float = 70.0
    strong_conviction_min_profit_partial_pct: float = 1.0
    strong_entry_profit_giveback_trigger_pct: float = 60.0
    weak_entry_profit_giveback_trigger_pct: float = 35.0
    weak_entry_min_profit_partial_pct: float = 0.35

    # Proactive profit capture
    proactive_profit_capture_enabled: bool = True
    proactive_strong_min_peak_pct: float = 0.45
    proactive_strong_min_current_pct: float = 0.20
    proactive_strong_giveback_pct: float = 45.0
    proactive_weak_min_peak_pct: float = 0.30
    proactive_weak_min_current_pct: float = 0.15
    proactive_weak_giveback_pct: float = 30.0

    # Exit-pattern pressure
    exit_pattern_profit_capture_enabled: bool = True
    exit_pattern_strong_min_peak_pct: float = 0.40
    exit_pattern_strong_min_current_pct: float = 0.18
    exit_pattern_weak_min_peak_pct: float = 0.25
    exit_pattern_weak_min_current_pct: float = 0.10
    exit_pattern_min_adverse_signals: int = 2
    exit_pattern_weak_giveback_pct: float = 20.0

    # Auto-buy coordination
    auto_buy_min_hold_minutes: float = 6.0
    auto_buy_min_hold_hard_loss_pct: float = -0.75
    auto_buy_strong_entry_ml_min: float = 55.0
    auto_buy_strong_entry_opportunity_min: float = 8.0

    def __post_init__(self) -> None:
        _check(
            0 < self.partial_sell_pct <= 1.0,
            "partial_sell_pct",
            "POSITION_MANAGER_PARTIAL_SELL_PCT",
            self.partial_sell_pct,
            "must be in (0, 1]",
        )
        _check(
            self.min_profit_partial_pct >= 0,
            "min_profit_partial_pct",
            "POSITION_MANAGER_MIN_PROFIT_PARTIAL_PCT",
            self.min_profit_partial_pct,
            "must be >= 0",
        )
        _check(
            self.profit_giveback_trigger_pct >= 0,
            "profit_giveback_trigger_pct",
            "POSITION_MANAGER_PROFIT_GIVEBACK_TRIGGER_PCT",
            self.profit_giveback_trigger_pct,
            "must be >= 0",
        )
        _check(
            self.breakeven_lock_trigger_pct >= 0,
            "breakeven_lock_trigger_pct",
            "BREAKEVEN_LOCK_TRIGGER_PCT",
            self.breakeven_lock_trigger_pct,
            "must be >= 0",
        )
        _check(
            self.breakeven_lock_floor_pct >= 0,
            "breakeven_lock_floor_pct",
            "BREAKEVEN_LOCK_FLOOR_PCT",
            self.breakeven_lock_floor_pct,
            "must be >= 0",
        )
        _check(
            self.full_exit_loss_pct <= 0,
            "full_exit_loss_pct",
            "POSITION_MANAGER_FULL_EXIT_LOSS_PCT",
            self.full_exit_loss_pct,
            "must be <= 0",
        )
        _check(
            self.vwap_loss_exit_pct <= 0,
            "vwap_loss_exit_pct",
            "POSITION_MANAGER_VWAP_LOSS_EXIT_PCT",
            self.vwap_loss_exit_pct,
            "must be <= 0",
        )
        _check(
            self.continuation_hard_loss_floor_pct <= 0,
            "continuation_hard_loss_floor_pct",
            "POSITION_MANAGER_CONTINUATION_HARD_LOSS_FLOOR_PCT",
            self.continuation_hard_loss_floor_pct,
            "must be <= 0",
        )
        _check(
            self.tier2_peak_pct > 0,
            "tier2_peak_pct",
            "POSITION_MANAGER_TIER2_PEAK_PCT",
            self.tier2_peak_pct,
            "must be > 0",
        )
        _check(
            self.tier3_peak_pct > self.tier2_peak_pct,
            "tier3_peak_pct",
            "POSITION_MANAGER_TIER3_PEAK_PCT",
            self.tier3_peak_pct,
            f"must be > tier2_peak_pct ({self.tier2_peak_pct})",
        )
        _check(
            self.retained_tier2_giveback_pct >= 0,
            "retained_tier2_giveback_pct",
            "POSITION_MANAGER_RETAINED_TIER2_GIVEBACK_PCT",
            self.retained_tier2_giveback_pct,
            "must be >= 0",
        )
        _check(
            self.retained_tier3_giveback_pct >= 0,
            "retained_tier3_giveback_pct",
            "POSITION_MANAGER_RETAINED_TIER3_GIVEBACK_PCT",
            self.retained_tier3_giveback_pct,
            "must be >= 0",
        )
        _check(
            self.lock_tier1_floor_pct < self.lock_tier1_peak_pct,
            "lock_tier1_floor_pct",
            "POSITION_MANAGER_LOCK_TIER1_FLOOR_PCT",
            self.lock_tier1_floor_pct,
            f"must be < lock_tier1_peak_pct ({self.lock_tier1_peak_pct})",
        )
        _check(
            self.lock_tier2_floor_pct < self.lock_tier2_peak_pct,
            "lock_tier2_floor_pct",
            "POSITION_MANAGER_LOCK_TIER2_FLOOR_PCT",
            self.lock_tier2_floor_pct,
            f"must be < lock_tier2_peak_pct ({self.lock_tier2_peak_pct})",
        )
        _check(
            self.lock_tier3_floor_pct < self.lock_tier3_peak_pct,
            "lock_tier3_floor_pct",
            "POSITION_MANAGER_LOCK_TIER3_FLOOR_PCT",
            self.lock_tier3_floor_pct,
            f"must be < lock_tier3_peak_pct ({self.lock_tier3_peak_pct})",
        )
        _check(
            self.lock_tier4_floor_pct < self.lock_tier4_peak_pct,
            "lock_tier4_floor_pct",
            "POSITION_MANAGER_LOCK_TIER4_FLOOR_PCT",
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
        promote_unexecutable_partials=env_bool("POSITION_MANAGER_PROMOTE_UNEXECUTABLE_PARTIALS", True),
        min_profit_partial_pct=env_float("POSITION_MANAGER_MIN_PROFIT_PARTIAL_PCT", 0.75),
        profit_giveback_trigger_pct=env_float("POSITION_MANAGER_PROFIT_GIVEBACK_TRIGGER_PCT", 50.0),
        breakeven_lock_trigger_pct=env_float("BREAKEVEN_LOCK_TRIGGER_PCT", 0.50),
        breakeven_lock_floor_pct=env_float("BREAKEVEN_LOCK_FLOOR_PCT", 0.05),
        weak_setup_breakeven_lock_trigger_pct=env_float(
            "WEAK_SETUP_BREAKEVEN_LOCK_TRIGGER_PCT", 0.35
        ),
        weak_setup_breakeven_lock_floor_pct=env_float("WEAK_SETUP_BREAKEVEN_LOCK_FLOOR_PCT", 0.02),
        full_exit_loss_pct=env_float("POSITION_MANAGER_FULL_EXIT_LOSS_PCT", -1.25),
        vwap_loss_exit_pct=env_float("POSITION_MANAGER_VWAP_LOSS_EXIT_PCT", -0.35),
        continuation_exit_check_enabled=env_bool(
            "POSITION_MANAGER_CONTINUATION_EXIT_CHECK_ENABLED", True
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
        momentum_strong_return_min_pct=env_float("POSITION_MOMENTUM_STRONG_RETURN_MIN_PCT", 1.0),
        momentum_strong_minutes_min=env_float("POSITION_MOMENTUM_STRONG_MINUTES_MIN", 20.0),
        momentum_retained_min_score=env_float("POSITION_MOMENTUM_RETAINED_MIN_SCORE", 3.0),
        momentum_retained_min_return_pct=env_float(
            "POSITION_MOMENTUM_RETAINED_MIN_RETURN_PCT", 0.25
        ),
        momentum_retained_min_vwap_dist_pct=env_float(
            "POSITION_MOMENTUM_RETAINED_MIN_VWAP_DIST_PCT", -0.25
        ),
        momentum_break_pullback_pct=env_float("POSITION_MOMENTUM_BREAK_PULLBACK_PCT", -0.75),
        momentum_break_vwap_dist_pct=env_float("POSITION_MOMENTUM_BREAK_VWAP_DIST_PCT", -0.35),
        momentum_break_15m_pct=env_float("POSITION_MOMENTUM_BREAK_15M_PCT", -0.35),
        momentum_break_30m_pct=env_float("POSITION_MOMENTUM_BREAK_30M_PCT", -0.50),
        profit_capture_enabled=env_bool("POSITION_MANAGER_PROFIT_CAPTURE_ENABLED", True),
        tier2_peak_pct=env_float("POSITION_MANAGER_TIER2_PEAK_PCT", 1.50),
        tier3_peak_pct=env_float("POSITION_MANAGER_TIER3_PEAK_PCT", 3.00),
        retained_tier2_giveback_pct=env_float("POSITION_MANAGER_RETAINED_TIER2_GIVEBACK_PCT", 60.0),
        retained_tier3_giveback_pct=env_float("POSITION_MANAGER_RETAINED_TIER3_GIVEBACK_PCT", 45.0),
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
        bad_entry_containment_enabled=env_bool(
            "POSITION_MANAGER_BAD_ENTRY_CONTAINMENT_ENABLED", True
        ),
        bad_entry_containment_loss_pct=env_float(
            "POSITION_MANAGER_BAD_ENTRY_CONTAINMENT_LOSS_PCT", -0.65
        ),
        bad_entry_containment_max_peak_pct=env_float(
            "POSITION_MANAGER_BAD_ENTRY_CONTAINMENT_MAX_PEAK_PCT", 0.15
        ),
        peak_lock_tier1_peak_pct=env_float("POSITION_MANAGER_PEAK_LOCK_TIER1_PEAK_PCT", 0.30),
        peak_lock_tier1_floor_pct=env_float("POSITION_MANAGER_PEAK_LOCK_TIER1_FLOOR_PCT", 0.10),
        peak_lock_tier2_peak_pct=env_float("POSITION_MANAGER_PEAK_LOCK_TIER2_PEAK_PCT", 0.60),
        peak_lock_tier2_floor_pct=env_float("POSITION_MANAGER_PEAK_LOCK_TIER2_FLOOR_PCT", 0.30),
        peak_lock_tier3_peak_pct=env_float("POSITION_MANAGER_PEAK_LOCK_TIER3_PEAK_PCT", 1.00),
        peak_lock_tier3_floor_pct=env_float("POSITION_MANAGER_PEAK_LOCK_TIER3_FLOOR_PCT", 0.45),
        weak_peak_lock_tier1_peak_pct=env_float(
            "POSITION_MANAGER_WEAK_PEAK_LOCK_TIER1_PEAK_PCT", 0.30
        ),
        weak_peak_lock_tier1_floor_pct=env_float(
            "POSITION_MANAGER_WEAK_PEAK_LOCK_TIER1_FLOOR_PCT", 0.15
        ),
        weak_peak_lock_tier2_peak_pct=env_float(
            "POSITION_MANAGER_WEAK_PEAK_LOCK_TIER2_PEAK_PCT", 0.50
        ),
        weak_peak_lock_tier2_floor_pct=env_float(
            "POSITION_MANAGER_WEAK_PEAK_LOCK_TIER2_FLOOR_PCT", 0.35
        ),
        strong_conviction_profit_giveback_trigger_pct=env_float(
            "POSITION_MANAGER_STRONG_CONVICTION_GIVEBACK_TRIGGER_PCT", 70.0
        ),
        strong_conviction_min_profit_partial_pct=env_float(
            "POSITION_MANAGER_STRONG_CONVICTION_MIN_PROFIT_PARTIAL_PCT", 1.0
        ),
        strong_entry_profit_giveback_trigger_pct=env_float(
            "POSITION_MANAGER_STRONG_ENTRY_PROFIT_GIVEBACK_PCT", 60.0
        ),
        weak_entry_profit_giveback_trigger_pct=env_float(
            "POSITION_MANAGER_WEAK_ENTRY_PROFIT_GIVEBACK_PCT", 35.0
        ),
        weak_entry_min_profit_partial_pct=env_float(
            "POSITION_MANAGER_WEAK_ENTRY_MIN_PROFIT_PARTIAL_PCT", 0.35
        ),
        proactive_profit_capture_enabled=env_bool(
            "POSITION_MANAGER_PROACTIVE_PROFIT_CAPTURE_ENABLED", True
        ),
        proactive_strong_min_peak_pct=env_float(
            "POSITION_MANAGER_PROACTIVE_STRONG_MIN_PEAK_PCT", 0.45
        ),
        proactive_strong_min_current_pct=env_float(
            "POSITION_MANAGER_PROACTIVE_STRONG_MIN_CURRENT_PCT", 0.20
        ),
        proactive_strong_giveback_pct=env_float(
            "POSITION_MANAGER_PROACTIVE_STRONG_GIVEBACK_PCT", 45.0
        ),
        proactive_weak_min_peak_pct=env_float("POSITION_MANAGER_PROACTIVE_WEAK_MIN_PEAK_PCT", 0.30),
        proactive_weak_min_current_pct=env_float(
            "POSITION_MANAGER_PROACTIVE_WEAK_MIN_CURRENT_PCT", 0.15
        ),
        proactive_weak_giveback_pct=env_float("POSITION_MANAGER_PROACTIVE_WEAK_GIVEBACK_PCT", 30.0),
        exit_pattern_profit_capture_enabled=env_bool(
            "POSITION_MANAGER_EXIT_PATTERN_PROFIT_CAPTURE_ENABLED", True
        ),
        exit_pattern_strong_min_peak_pct=env_float(
            "POSITION_MANAGER_EXIT_PATTERN_STRONG_MIN_PEAK_PCT", 0.40
        ),
        exit_pattern_strong_min_current_pct=env_float(
            "POSITION_MANAGER_EXIT_PATTERN_STRONG_MIN_CURRENT_PCT", 0.18
        ),
        exit_pattern_weak_min_peak_pct=env_float(
            "POSITION_MANAGER_EXIT_PATTERN_WEAK_MIN_PEAK_PCT", 0.25
        ),
        exit_pattern_weak_min_current_pct=env_float(
            "POSITION_MANAGER_EXIT_PATTERN_WEAK_MIN_CURRENT_PCT", 0.10
        ),
        exit_pattern_min_adverse_signals=env_int(
            "POSITION_MANAGER_EXIT_PATTERN_MIN_ADVERSE_SIGNALS", 2
        ),
        exit_pattern_weak_giveback_pct=env_float(
            "POSITION_MANAGER_EXIT_PATTERN_WEAK_GIVEBACK_PCT", 20.0
        ),
        auto_buy_min_hold_minutes=env_float("POSITION_MANAGER_AUTO_BUY_MIN_HOLD_MINUTES", 6.0),
        auto_buy_min_hold_hard_loss_pct=env_float(
            "POSITION_MANAGER_AUTO_BUY_MIN_HOLD_HARD_LOSS_PCT", -0.75
        ),
        auto_buy_strong_entry_ml_min=env_float(
            "POSITION_MANAGER_AUTO_BUY_STRONG_ENTRY_ML_MIN", 55.0
        ),
        auto_buy_strong_entry_opportunity_min=env_float(
            "POSITION_MANAGER_AUTO_BUY_STRONG_ENTRY_OPPORTUNITY_MIN", 8.0
        ),
    )
    kwargs.update(overrides)
    return PositionManagerConfig(**kwargs)
