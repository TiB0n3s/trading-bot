"""Auto-buy manager configuration."""

from __future__ import annotations

import os
from dataclasses import dataclass

from config._env import _check, env_bool, env_float, env_int, env_str


def _paper_runtime_default(paper_value, live_value):
    mode = os.getenv("EXECUTION_MODE", "paper").strip().lower()
    return paper_value if mode in {"paper", "dry_run"} else live_value


@dataclass(frozen=True)
class AutoBuyConfig:
    # Order execution
    live_buys: bool = False
    signal_mode: str = "legacy_source_gate"
    tradingview_alerts_deprecated: bool = False
    position_size_pct: float = 0.50
    stop_loss_pct: float = 1.00
    take_profit_pct: float = 2.00
    max_orders_per_run: int = 1
    max_active_positions: int = 3
    max_daily_orders: int = 12
    max_signals_per_symbol: int = 2

    # Score thresholds
    min_score: float = 13.0
    watch_score: float = 7.0
    paper_strong_evidence_promotion_enabled: bool = True
    paper_strong_evidence_score_buffer: float = 3.0
    paper_strong_evidence_min_setup_score: float = 50.0
    paper_strong_evidence_min_ml_score: float = 50.0
    paper_strong_evidence_min_session_score: float = 5.0
    paper_exploration_fallback_enabled: bool = True
    paper_exploration_min_score: float = 10.0
    paper_exploration_min_setup_score: float = 50.0
    paper_exploration_min_session_score: float = 5.0
    paper_exploration_min_ml_score: float = 50.0

    # Setup/session score shaping
    extended_vwap_caution_pct: float = 1.50
    unclassified_extended_block_pct: float = 1.50
    watch_setup_strong_buy_enabled: bool = True
    early_build_enabled: bool = True
    early_build_max_session_return_pct: float = 0.90
    early_build_max_vwap_dist_pct: float = 0.70
    early_build_min_setup_score: float = 50.0
    mature_chase_enabled: bool = True
    mature_chase_session_return_pct: float = 1.50
    mature_chase_vwap_dist_pct: float = 1.00
    extreme_chase_block_session_return_pct: float = 2.50
    extreme_chase_block_vwap_dist_pct: float = 1.25

    # ML weak-block gates
    ml_weak_block_enabled: bool = True
    ml_weak_block_score: float = 45.0
    ml_weak_block_min_sample_size: int = 20
    ml_weak_bucket_block_enabled: bool = True

    # Learned tiebreaker
    learned_tiebreaker_enabled: bool = True
    learned_tiebreaker_min_sample_size: int = 10
    learned_tiebreaker_min_win_rate: float = 0.55
    learned_tiebreaker_min_avg_return_pct: float = 0.20
    learned_tiebreaker_min_avg_mfe_pct: float = 1.00
    learned_tiebreaker_max_avg_mae_pct: float = -1.50
    learned_tiebreaker_lookback_days: int = 10
    learned_tiebreaker_max_historical_rows: int = 2000
    learned_tiebreaker_max_threshold_gap: float = 6.0

    # Layered ML
    layered_ml_enabled: bool = True
    layered_ml_promotion_enabled: bool = True
    layered_ml_veto_hard_block_enabled: bool = True
    layered_ml_min_promotion_confidence: float = 65.0
    layered_ml_min_veto_confidence: float = 55.0
    layered_ml_score_boost: float = 3.0
    layered_ml_pass_score_boost: float = 1.0
    layered_ml_watch_score_penalty: float = 2.0
    layered_ml_veto_score_penalty: float = 8.0
    layered_ml_max_threshold_gap: float = 6.0

    # Timing guards
    cooldown_minutes: int = 60
    session_buffer_minutes: int = 10
    max_symbols_per_run: int = 20
    timing_log_enabled: bool = True
    score_detail_log_enabled: bool = True
    intraday_feedback_enabled: bool = True

    # Shared cooldown constants (mirrored from app.py gate)
    app_buy_cooldown_minutes: int = 15
    app_recent_sell_cooldown_minutes: int = 30
    cash_safe_max_new_buys_per_symbol_per_day: int = 1

    # Bucking-tape thresholds — full-session path
    bucking_tape_min_session_return_pct: float = 2.0
    bucking_tape_min_relative_strength: float = 0.30

    # Bucking-tape thresholds — acceleration path
    bucking_tape_min_accel_pct: float = 0.04
    bucking_tape_min_volume_ratio: float = 1.8
    bucking_tape_min_early_session_return_pct: float = 0.75

    def __post_init__(self) -> None:
        _check(
            self.position_size_pct > 0,
            "position_size_pct",
            "AUTO_BUY_POSITION_SIZE_PCT",
            self.position_size_pct,
            "must be > 0",
        )
        _check(
            self.stop_loss_pct > 0,
            "stop_loss_pct",
            "AUTO_BUY_STOP_LOSS_PCT",
            self.stop_loss_pct,
            "must be > 0",
        )
        _check(
            self.take_profit_pct >= 0,
            "take_profit_pct",
            "AUTO_BUY_TAKE_PROFIT_PCT",
            self.take_profit_pct,
            "must be >= 0",
        )
        _check(
            self.max_orders_per_run >= 1,
            "max_orders_per_run",
            "AUTO_BUY_MAX_ORDERS_PER_RUN",
            self.max_orders_per_run,
            "must be >= 1",
        )
        _check(
            self.max_active_positions >= 1,
            "max_active_positions",
            "AUTO_BUY_MAX_ACTIVE_POSITIONS",
            self.max_active_positions,
            "must be >= 1",
        )
        _check(
            self.max_daily_orders >= 1,
            "max_daily_orders",
            "AUTO_BUY_MAX_DAILY_ORDERS",
            self.max_daily_orders,
            "must be >= 1",
        )
        _check(
            self.max_signals_per_symbol >= 1,
            "max_signals_per_symbol",
            "AUTO_BUY_MAX_SIGNALS_PER_SYMBOL",
            self.max_signals_per_symbol,
            "must be >= 1",
        )
        _check(
            self.min_score >= 0,
            "min_score",
            "AUTO_BUY_MIN_SCORE",
            self.min_score,
            "must be >= 0",
        )
        _check(
            self.watch_score >= 0,
            "watch_score",
            "AUTO_BUY_WATCH_SCORE",
            self.watch_score,
            "must be >= 0",
        )
        _check(
            self.paper_strong_evidence_score_buffer >= 0,
            "paper_strong_evidence_score_buffer",
            "AUTO_BUY_PAPER_STRONG_EVIDENCE_SCORE_BUFFER",
            self.paper_strong_evidence_score_buffer,
            "must be >= 0",
        )
        _check(
            self.paper_strong_evidence_min_setup_score >= 0,
            "paper_strong_evidence_min_setup_score",
            "AUTO_BUY_PAPER_STRONG_EVIDENCE_MIN_SETUP_SCORE",
            self.paper_strong_evidence_min_setup_score,
            "must be >= 0",
        )
        _check(
            self.paper_strong_evidence_min_ml_score >= 0,
            "paper_strong_evidence_min_ml_score",
            "AUTO_BUY_PAPER_STRONG_EVIDENCE_MIN_ML_SCORE",
            self.paper_strong_evidence_min_ml_score,
            "must be >= 0",
        )
        _check(
            self.paper_strong_evidence_min_session_score >= 0,
            "paper_strong_evidence_min_session_score",
            "AUTO_BUY_PAPER_STRONG_EVIDENCE_MIN_SESSION_SCORE",
            self.paper_strong_evidence_min_session_score,
            "must be >= 0",
        )
        _check(
            self.cooldown_minutes >= 1,
            "cooldown_minutes",
            "AUTO_BUY_COOLDOWN_MINUTES",
            self.cooldown_minutes,
            "must be >= 1",
        )
        _check(
            self.session_buffer_minutes >= 0,
            "session_buffer_minutes",
            "AUTO_BUY_SESSION_BUFFER_MINUTES",
            self.session_buffer_minutes,
            "must be >= 0",
        )
        _check(
            self.app_buy_cooldown_minutes >= 1,
            "app_buy_cooldown_minutes",
            "ORDER_COOLDOWN_MINUTES",
            self.app_buy_cooldown_minutes,
            "must be >= 1",
        )
        _check(
            self.app_recent_sell_cooldown_minutes >= 1,
            "app_recent_sell_cooldown_minutes",
            "RECENT_SELL_COOLDOWN_MINUTES",
            self.app_recent_sell_cooldown_minutes,
            "must be >= 1",
        )
        _check(
            self.cash_safe_max_new_buys_per_symbol_per_day >= 1,
            "cash_safe_max_new_buys_per_symbol_per_day",
            "CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY",
            self.cash_safe_max_new_buys_per_symbol_per_day,
            "must be >= 1",
        )
        _check(
            self.bucking_tape_min_volume_ratio >= 0,
            "bucking_tape_min_volume_ratio",
            "AUTO_BUY_BUCKING_TAPE_MIN_VOLUME_RATIO",
            self.bucking_tape_min_volume_ratio,
            "must be >= 0",
        )
        _check(
            self.signal_mode in {"legacy_source_gate", "internal_all", "bar_all", "all_internal"},
            "signal_mode",
            "AUTO_BUY_SIGNAL_MODE",
            self.signal_mode,
            "must be one of legacy_source_gate, internal_all, bar_all, all_internal",
        )


def load_auto_buy_config(**overrides) -> AutoBuyConfig:
    """Construct AutoBuyConfig from current env, with optional kwarg overrides.

    Production code uses the ``auto_buy_cfg`` singleton from ``config``.
    Tests call this factory directly after patching env (or pass overrides)
    to get a fresh instance without touching the singleton.

    Example::

        cfg = load_auto_buy_config(live_buys=False, min_score=15.0)
    """
    kwargs: dict = dict(
        live_buys=env_bool("AUTO_BUY_LIVE_BUYS", False),
        signal_mode=env_str("AUTO_BUY_SIGNAL_MODE", "legacy_source_gate").lower(),
        tradingview_alerts_deprecated=env_bool("TRADINGVIEW_ALERTS_DEPRECATED", False),
        position_size_pct=env_float("AUTO_BUY_POSITION_SIZE_PCT", 0.50),
        stop_loss_pct=env_float("AUTO_BUY_STOP_LOSS_PCT", 1.00),
        take_profit_pct=env_float("AUTO_BUY_TAKE_PROFIT_PCT", 2.00),
        max_orders_per_run=env_int(
            "AUTO_BUY_MAX_ORDERS_PER_RUN", int(_paper_runtime_default(3, 1))
        ),
        max_active_positions=env_int(
            "AUTO_BUY_MAX_ACTIVE_POSITIONS", int(_paper_runtime_default(8, 3))
        ),
        max_daily_orders=env_int("AUTO_BUY_MAX_DAILY_ORDERS", int(_paper_runtime_default(30, 12))),
        max_signals_per_symbol=env_int("AUTO_BUY_MAX_SIGNALS_PER_SYMBOL", 2),
        min_score=env_float("AUTO_BUY_MIN_SCORE", 13.0),
        watch_score=env_float("AUTO_BUY_WATCH_SCORE", 7.0),
        paper_strong_evidence_promotion_enabled=env_bool(
            "AUTO_BUY_PAPER_STRONG_EVIDENCE_PROMOTION_ENABLED",
            bool(_paper_runtime_default(True, False)),
        ),
        paper_strong_evidence_score_buffer=env_float(
            "AUTO_BUY_PAPER_STRONG_EVIDENCE_SCORE_BUFFER", 3.0
        ),
        paper_strong_evidence_min_setup_score=env_float(
            "AUTO_BUY_PAPER_STRONG_EVIDENCE_MIN_SETUP_SCORE", 50.0
        ),
        paper_strong_evidence_min_ml_score=env_float(
            "AUTO_BUY_PAPER_STRONG_EVIDENCE_MIN_ML_SCORE", 50.0
        ),
        paper_strong_evidence_min_session_score=env_float(
            "AUTO_BUY_PAPER_STRONG_EVIDENCE_MIN_SESSION_SCORE", 5.0
        ),
        paper_exploration_fallback_enabled=env_bool(
            "AUTO_BUY_PAPER_EXPLORATION_FALLBACK_ENABLED",
            bool(_paper_runtime_default(True, False)),
        ),
        paper_exploration_min_score=env_float("AUTO_BUY_PAPER_EXPLORATION_MIN_SCORE", 10.0),
        paper_exploration_min_setup_score=env_float(
            "AUTO_BUY_PAPER_EXPLORATION_MIN_SETUP_SCORE", 50.0
        ),
        paper_exploration_min_session_score=env_float(
            "AUTO_BUY_PAPER_EXPLORATION_MIN_SESSION_SCORE", 5.0
        ),
        paper_exploration_min_ml_score=env_float("AUTO_BUY_PAPER_EXPLORATION_MIN_ML_SCORE", 50.0),
        extended_vwap_caution_pct=env_float("AUTO_BUY_EXTENDED_VWAP_CAUTION_PCT", 1.50),
        unclassified_extended_block_pct=env_float("AUTO_BUY_UNCLASSIFIED_EXTENDED_BLOCK_PCT", 1.50),
        watch_setup_strong_buy_enabled=env_bool(
            "AUTO_BUY_WATCH_SETUP_STRONG_BUY_ENABLED",
            bool(_paper_runtime_default(True, False)),
        ),
        early_build_enabled=env_bool("AUTO_BUY_EARLY_BUILD_ENABLED", True),
        early_build_max_session_return_pct=env_float(
            "AUTO_BUY_EARLY_BUILD_MAX_SESSION_RETURN_PCT", 0.90
        ),
        early_build_max_vwap_dist_pct=env_float("AUTO_BUY_EARLY_BUILD_MAX_VWAP_DIST_PCT", 0.70),
        early_build_min_setup_score=env_float("AUTO_BUY_EARLY_BUILD_MIN_SETUP_SCORE", 50.0),
        mature_chase_enabled=env_bool("AUTO_BUY_MATURE_CHASE_ENABLED", True),
        mature_chase_session_return_pct=env_float("AUTO_BUY_MATURE_CHASE_SESSION_RETURN_PCT", 1.50),
        mature_chase_vwap_dist_pct=env_float("AUTO_BUY_MATURE_CHASE_VWAP_DIST_PCT", 1.00),
        extreme_chase_block_session_return_pct=env_float(
            "AUTO_BUY_EXTREME_CHASE_BLOCK_SESSION_RETURN_PCT", 2.50
        ),
        extreme_chase_block_vwap_dist_pct=env_float(
            "AUTO_BUY_EXTREME_CHASE_BLOCK_VWAP_DIST_PCT", 1.25
        ),
        ml_weak_block_enabled=env_bool("AUTO_BUY_ML_WEAK_BLOCK_ENABLED", True),
        ml_weak_block_score=env_float("AUTO_BUY_ML_WEAK_BLOCK_SCORE", 45.0),
        ml_weak_block_min_sample_size=env_int("AUTO_BUY_ML_WEAK_BLOCK_MIN_SAMPLE_SIZE", 20),
        ml_weak_bucket_block_enabled=env_bool("AUTO_BUY_ML_WEAK_BUCKET_BLOCK_ENABLED", True),
        learned_tiebreaker_enabled=env_bool("AUTO_BUY_LEARNED_TIEBREAKER_ENABLED", True),
        learned_tiebreaker_min_sample_size=env_int(
            "AUTO_BUY_LEARNED_TIEBREAKER_MIN_SAMPLE_SIZE",
            int(_paper_runtime_default(10, 25)),
        ),
        learned_tiebreaker_min_win_rate=env_float("AUTO_BUY_LEARNED_TIEBREAKER_MIN_WIN_RATE", 0.55),
        learned_tiebreaker_min_avg_return_pct=env_float(
            "AUTO_BUY_LEARNED_TIEBREAKER_MIN_AVG_RETURN_PCT", 0.20
        ),
        learned_tiebreaker_min_avg_mfe_pct=env_float(
            "AUTO_BUY_LEARNED_TIEBREAKER_MIN_AVG_MFE_PCT", 1.00
        ),
        learned_tiebreaker_max_avg_mae_pct=env_float(
            "AUTO_BUY_LEARNED_TIEBREAKER_MAX_AVG_MAE_PCT", -1.50
        ),
        learned_tiebreaker_lookback_days=env_int("AUTO_BUY_LEARNED_TIEBREAKER_LOOKBACK_DAYS", 10),
        learned_tiebreaker_max_historical_rows=env_int(
            "AUTO_BUY_LEARNED_TIEBREAKER_MAX_HISTORICAL_ROWS", 2000
        ),
        learned_tiebreaker_max_threshold_gap=env_float(
            "AUTO_BUY_LEARNED_TIEBREAKER_MAX_THRESHOLD_GAP",
            float(_paper_runtime_default(6.0, 4.0)),
        ),
        layered_ml_enabled=env_bool(
            "AUTO_BUY_LAYERED_ML_ENABLED",
            bool(_paper_runtime_default(True, False)),
        ),
        layered_ml_promotion_enabled=env_bool(
            "AUTO_BUY_LAYERED_ML_PROMOTION_ENABLED",
            bool(_paper_runtime_default(True, False)),
        ),
        layered_ml_veto_hard_block_enabled=env_bool(
            "AUTO_BUY_LAYERED_ML_VETO_HARD_BLOCK_ENABLED",
            bool(_paper_runtime_default(True, False)),
        ),
        layered_ml_min_promotion_confidence=env_float(
            "AUTO_BUY_LAYERED_ML_MIN_PROMOTION_CONFIDENCE", 65.0
        ),
        layered_ml_min_veto_confidence=env_float("AUTO_BUY_LAYERED_ML_MIN_VETO_CONFIDENCE", 55.0),
        layered_ml_score_boost=env_float("AUTO_BUY_LAYERED_ML_SCORE_BOOST", 3.0),
        layered_ml_pass_score_boost=env_float("AUTO_BUY_LAYERED_ML_PASS_SCORE_BOOST", 1.0),
        layered_ml_watch_score_penalty=env_float("AUTO_BUY_LAYERED_ML_WATCH_SCORE_PENALTY", 2.0),
        layered_ml_veto_score_penalty=env_float("AUTO_BUY_LAYERED_ML_VETO_SCORE_PENALTY", 8.0),
        layered_ml_max_threshold_gap=env_float("AUTO_BUY_LAYERED_ML_MAX_THRESHOLD_GAP", 6.0),
        cooldown_minutes=env_int("AUTO_BUY_COOLDOWN_MINUTES", 60),
        session_buffer_minutes=env_int("AUTO_BUY_SESSION_BUFFER_MINUTES", 10),
        max_symbols_per_run=env_int("AUTO_BUY_MAX_SYMBOLS_PER_RUN", 20),
        timing_log_enabled=env_bool("AUTO_BUY_TIMING_LOG_ENABLED", True),
        score_detail_log_enabled=env_bool("AUTO_BUY_SCORE_DETAIL_LOG_ENABLED", True),
        intraday_feedback_enabled=env_bool("AUTO_BUY_INTRADAY_FEEDBACK_ENABLED", True),
        app_buy_cooldown_minutes=env_int("ORDER_COOLDOWN_MINUTES", 15),
        app_recent_sell_cooldown_minutes=env_int("RECENT_SELL_COOLDOWN_MINUTES", 30),
        cash_safe_max_new_buys_per_symbol_per_day=env_int(
            "CASH_SAFE_MAX_NEW_BUYS_PER_SYMBOL_PER_DAY", 1
        ),
        bucking_tape_min_session_return_pct=env_float(
            "AUTO_BUY_BUCKING_TAPE_MIN_SESSION_RETURN_PCT", 2.0
        ),
        bucking_tape_min_relative_strength=env_float(
            "AUTO_BUY_BUCKING_TAPE_MIN_RELATIVE_STRENGTH", 0.30
        ),
        bucking_tape_min_accel_pct=env_float("AUTO_BUY_BUCKING_TAPE_MIN_ACCEL_PCT", 0.04),
        bucking_tape_min_volume_ratio=env_float("AUTO_BUY_BUCKING_TAPE_MIN_VOLUME_RATIO", 1.8),
        bucking_tape_min_early_session_return_pct=env_float(
            "AUTO_BUY_BUCKING_TAPE_MIN_EARLY_SESSION_RETURN_PCT", 0.75
        ),
    )
    kwargs.update(overrides)
    return AutoBuyConfig(**kwargs)
