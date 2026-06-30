"""
Tests for config factory functions (**overrides pattern).

Verifies four properties for every domain:
  1. Override bypasses env — kwarg wins regardless of process env
  2. Override goes through validation — bad kwarg raises ValueError
  3. Partial override preserves defaults — untouched fields keep their values
  4. No env dependency unless intentionally patched — factories are safe to
     call in any env, including CI with no trading-bot env vars set

Run:
  python3 tests/test_config_factories.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


class _CleanEnv:
    """Context manager: removes a set of env vars, restores them on exit."""

    def __init__(self, *names: str) -> None:
        self._names = names
        self._saved: dict[str, str | None] = {}

    def __enter__(self) -> "_CleanEnv":
        for name in self._names:
            self._saved[name] = os.environ.pop(name, None)
        return self

    def __exit__(self, *_) -> None:
        for name, val in self._saved.items():
            if val is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = val


class _PatchEnv:
    """Context manager: sets env vars, restores originals on exit."""

    def __init__(self, **pairs: str) -> None:
        self._pairs = pairs
        self._saved: dict[str, str | None] = {}

    def __enter__(self) -> "_PatchEnv":
        for name, val in self._pairs.items():
            self._saved[name] = os.environ.get(name)
            os.environ[name] = val
        return self

    def __exit__(self, *_) -> None:
        for name, original in self._saved.items():
            if original is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = original


def _raises(exc_type, fn, *args, **kwargs) -> Exception:
    try:
        fn(*args, **kwargs)
    except exc_type as exc:
        return exc
    raise AssertionError(f"Expected {exc_type.__name__} but no exception was raised")


# ---------------------------------------------------------------------------
# Import factories (no singletons touched)
# ---------------------------------------------------------------------------

from config.auto_buy import AutoBuyConfig, load_auto_buy_config  # noqa: E402
from config.auto_sell import AutoSellConfig, load_auto_sell_config  # noqa: E402
from config.ml import MLConfig, load_ml_config  # noqa: E402
from config.position_manager import (  # noqa: E402
    PositionManagerConfig,
    load_position_manager_config,
)
from config.risk import RiskConfig, load_risk_config  # noqa: E402
from config.signal import SignalConfig, load_signal_config  # noqa: E402

RISK_ENV_VARS = [
    "MACRO_POSITION_COUNT_FLOOR",
    "PORTFOLIO_ROTATION_ENABLED",
    "PORTFOLIO_REPLACEMENT_MODE",
    "RISK_POLICY_MODE",
    "REGIME_CIRCUIT_BREAKER_MODE",
    "ENFORCE_SESSION_MOMENTUM_GATE",
    "ENFORCE_ADAPTIVE_CHURN_REENTRY",
]
AUTO_BUY_ENV_VARS = [
    "EXECUTION_MODE",
    "AUTO_BUY_LIVE_BUYS",
    "AUTO_BUY_MIN_SCORE",
    "AUTO_BUY_POSITION_SIZE_PCT",
    "AUTO_BUY_STOP_LOSS_PCT",
    "AUTO_BUY_TAKE_PROFIT_PCT",
    "AUTO_BUY_MAX_ACTIVE_POSITIONS",
    "AUTO_BUY_MAX_DAILY_ORDERS",
    "AUTO_BUY_COOLDOWN_MINUTES",
    "AUTO_BUY_BUCKING_TAPE_MIN_VOLUME_RATIO",
    "AUTO_BUY_SIGNAL_MODE",
    "TRADINGVIEW_ALERTS_DEPRECATED",
    "AUTO_BUY_MAX_ORDERS_PER_RUN",
    "AUTO_BUY_MAX_SIGNALS_PER_SYMBOL",
    "AUTO_BUY_PAPER_STRONG_EVIDENCE_PROMOTION_ENABLED",
    "AUTO_BUY_PAPER_STRONG_EVIDENCE_SCORE_BUFFER",
    "AUTO_BUY_PAPER_STRONG_EVIDENCE_MIN_SETUP_SCORE",
    "AUTO_BUY_PAPER_STRONG_EVIDENCE_MIN_ML_SCORE",
    "AUTO_BUY_PAPER_STRONG_EVIDENCE_MIN_SESSION_SCORE",
    "AUTO_BUY_PAPER_EXPLORATION_FALLBACK_ENABLED",
    "AUTO_BUY_PAPER_EXPLORATION_MIN_SCORE",
    "AUTO_BUY_PAPER_EXPLORATION_MIN_SETUP_SCORE",
    "AUTO_BUY_PAPER_EXPLORATION_MIN_SESSION_SCORE",
    "AUTO_BUY_PAPER_EXPLORATION_MIN_ML_SCORE",
    "AUTO_BUY_EXTENDED_VWAP_CAUTION_PCT",
    "AUTO_BUY_UNCLASSIFIED_EXTENDED_BLOCK_PCT",
    "AUTO_BUY_WATCH_SETUP_STRONG_BUY_ENABLED",
    "AUTO_BUY_EARLY_BUILD_ENABLED",
    "AUTO_BUY_EARLY_BUILD_MAX_SESSION_RETURN_PCT",
    "AUTO_BUY_EARLY_BUILD_MAX_VWAP_DIST_PCT",
    "AUTO_BUY_EARLY_BUILD_MIN_SETUP_SCORE",
    "AUTO_BUY_MATURE_CHASE_ENABLED",
    "AUTO_BUY_MATURE_CHASE_SESSION_RETURN_PCT",
    "AUTO_BUY_MATURE_CHASE_VWAP_DIST_PCT",
    "AUTO_BUY_EXTREME_CHASE_BLOCK_SESSION_RETURN_PCT",
    "AUTO_BUY_EXTREME_CHASE_BLOCK_VWAP_DIST_PCT",
    "AUTO_BUY_ML_WEAK_BLOCK_ENABLED",
    "AUTO_BUY_ML_WEAK_BLOCK_SCORE",
    "AUTO_BUY_ML_WEAK_BLOCK_MIN_SAMPLE_SIZE",
    "AUTO_BUY_ML_WEAK_BUCKET_BLOCK_ENABLED",
    "AUTO_BUY_LEARNED_TIEBREAKER_ENABLED",
    "AUTO_BUY_LEARNED_TIEBREAKER_MIN_SAMPLE_SIZE",
    "AUTO_BUY_LEARNED_TIEBREAKER_MIN_WIN_RATE",
    "AUTO_BUY_LEARNED_TIEBREAKER_MIN_AVG_RETURN_PCT",
    "AUTO_BUY_LEARNED_TIEBREAKER_MIN_AVG_MFE_PCT",
    "AUTO_BUY_LEARNED_TIEBREAKER_MAX_AVG_MAE_PCT",
    "AUTO_BUY_LEARNED_TIEBREAKER_LOOKBACK_DAYS",
    "AUTO_BUY_LEARNED_TIEBREAKER_MAX_HISTORICAL_ROWS",
    "AUTO_BUY_LEARNED_TIEBREAKER_MAX_THRESHOLD_GAP",
    "AUTO_BUY_INTRADAY_FEEDBACK_ENABLED",
    "AUTO_BUY_LAYERED_ML_ENABLED",
    "AUTO_BUY_LAYERED_ML_PROMOTION_ENABLED",
    "AUTO_BUY_LAYERED_ML_VETO_HARD_BLOCK_ENABLED",
    "AUTO_BUY_LAYERED_ML_MIN_PROMOTION_CONFIDENCE",
    "AUTO_BUY_LAYERED_ML_MIN_VETO_CONFIDENCE",
    "AUTO_BUY_LAYERED_ML_SCORE_BOOST",
    "AUTO_BUY_LAYERED_ML_PASS_SCORE_BOOST",
    "AUTO_BUY_LAYERED_ML_WATCH_SCORE_PENALTY",
    "AUTO_BUY_LAYERED_ML_VETO_SCORE_PENALTY",
    "AUTO_BUY_LAYERED_ML_MAX_THRESHOLD_GAP",
    "AUTO_BUY_MAX_SYMBOLS_PER_RUN",
    "AUTO_BUY_TIMING_LOG_ENABLED",
    "AUTO_BUY_SCORE_DETAIL_LOG_ENABLED",
]
AUTO_SELL_ENV_VARS = [
    "EXECUTION_MODE",
    "POSITION_MOMENTUM_AUTO_SELL",
    "POSITION_MOMENTUM_LAYERED_ML_ENABLED",
    "POSITION_MOMENTUM_LAYERED_ML_MIN_EXIT_CONFIDENCE",
    "POSITION_MOMENTUM_EMERGENCY_LOSS_PCT",
    "POSITION_MOMENTUM_FAILED_HIGH_RUN_LOSS_PCT",
    "POSITION_MOMENTUM_MIN_PROFIT_SELL_PCT",
    "POSITION_MOMENTUM_SEVERE_BREAKDOWN_SCORE",
]


# ===========================================================================
# SignalConfig
# ===========================================================================


def test_signal_override_bypasses_env():
    with _PatchEnv(PREDICTION_GATE_MODE="warn"):
        cfg = load_signal_config(prediction_gate_mode="block")
    assert cfg.prediction_gate_mode == "block"


def test_signal_override_goes_through_validation():
    exc = _raises(ValueError, load_signal_config, prediction_gate_mode="INVALID")
    assert "prediction_gate_mode" in str(exc)
    assert "PREDICTION_GATE_MODE" in str(exc)
    assert "INVALID" in str(exc)


def test_signal_partial_override_preserves_defaults():
    cfg = load_signal_config(session_max_trade_count=5)
    assert cfg.session_max_trade_count == 5
    assert cfg.prediction_gate_mode == SignalConfig.prediction_gate_mode
    assert cfg.one_bar_confirmation_timeout_seconds == (
        SignalConfig.one_bar_confirmation_timeout_seconds
    )


def test_signal_no_env_dependency():
    env_vars = [
        "PREDICTION_GATE_MODE",
        "PREDICTION_SOFT_AVOID_MIN_SAMPLE_SIZE",
        "ONE_BAR_CONFIRMATION_HOLD_ENABLED",
        "ONE_BAR_CONFIRMATION_TIMEOUT_SECONDS",
        "TAPE_EXCEPTION_ENABLED",
        "OPEN_MOMENTUM_FAST_LANE_ENABLED",
        "MAX_SIGNAL_PRICE_DRIFT_PCT",
        "MAX_BID_ASK_SPREAD_PCT",
        "SELL_CONTINUATION_CHECK_ENABLED",
        "SELL_CONTINUATION_MIN_SUPPORTS",
        "SESSION_MAX_TRADE_COUNT",
        "SIGNAL_WORKER_COUNT",
        "LATE_QUOTE_DELAY_MIN_BLOCKS",
    ]
    with _CleanEnv(*env_vars):
        cfg = load_signal_config()
    assert cfg.prediction_gate_mode == "warn"
    assert cfg.session_max_trade_count == 3
    # webhook_secret was removed from SignalConfig with the TradingView webhook
    # (commit 4e16642d); the operator secret now lives only in the env/auth path.


def test_signal_env_var_is_read_when_no_override():
    with _PatchEnv(PREDICTION_GATE_MODE="block"):
        cfg = load_signal_config()
    assert cfg.prediction_gate_mode == "block"


def test_signal_override_wins_over_env():
    with _PatchEnv(SESSION_MAX_TRADE_COUNT="10"):
        cfg_from_env = load_signal_config()
        cfg_overridden = load_signal_config(session_max_trade_count=2)
    assert cfg_from_env.session_max_trade_count == 10
    assert cfg_overridden.session_max_trade_count == 2


# ===========================================================================
# RiskConfig
# ===========================================================================


def test_risk_override_bypasses_env():
    with _CleanEnv(*RISK_ENV_VARS):
        with _PatchEnv(PORTFOLIO_ROTATION_ENABLED="false"):
            cfg = load_risk_config(portfolio_rotation_enabled=True)
    assert cfg.portfolio_rotation_enabled is True


def test_risk_override_goes_through_validation():
    with _CleanEnv(*RISK_ENV_VARS):
        exc = _raises(ValueError, load_risk_config, risk_policy_mode="live")
    assert "risk_policy_mode" in str(exc)
    assert "RISK_POLICY_MODE" in str(exc)


def test_risk_portfolio_replacement_accepts_live_rotation_mode():
    with _CleanEnv(*RISK_ENV_VARS):
        cfg = load_risk_config(portfolio_replacement_mode="live_rotation")
    assert cfg.portfolio_replacement_mode == "live_rotation"


def test_risk_circuit_breaker_mode_validation():
    with _CleanEnv(*RISK_ENV_VARS):
        cfg = load_risk_config(regime_circuit_breaker_mode="block")
    assert cfg.regime_circuit_breaker_mode == "block"

    with _CleanEnv(*RISK_ENV_VARS):
        exc = _raises(ValueError, load_risk_config, regime_circuit_breaker_mode="panic")
    assert "regime_circuit_breaker_mode" in str(exc)
    assert "REGIME_CIRCUIT_BREAKER_MODE" in str(exc)


def test_risk_override_loss_pct_sign():
    with _CleanEnv(*RISK_ENV_VARS):
        exc = _raises(
            ValueError,
            load_risk_config,
            portfolio_replacement_weak_holding_plpc=0.5,
        )
    assert "portfolio_replacement_weak_holding_plpc" in str(exc)
    assert "<= 0" in str(exc)


def test_risk_partial_override_preserves_defaults():
    with _CleanEnv(*RISK_ENV_VARS):
        cfg = load_risk_config(portfolio_rotation_max_per_day=5)
    assert cfg.portfolio_rotation_max_per_day == 5
    assert cfg.macro_position_count_floor == RiskConfig.macro_position_count_floor
    assert cfg.portfolio_rotation_min_hold_minutes == (
        RiskConfig.portfolio_rotation_min_hold_minutes
    )


def test_risk_no_env_dependency():
    with _CleanEnv(*RISK_ENV_VARS):
        cfg = load_risk_config()
    assert cfg.macro_position_count_floor == 500.0
    assert cfg.portfolio_rotation_enabled is False
    assert cfg.risk_policy_mode == "compare"
    assert cfg.regime_circuit_breaker_mode == "off"


def test_risk_circuit_breaker_env_var_is_read_when_no_override():
    with _CleanEnv(*RISK_ENV_VARS):
        with _PatchEnv(REGIME_CIRCUIT_BREAKER_MODE="warn"):
            cfg = load_risk_config()
    assert cfg.regime_circuit_breaker_mode == "warn"


# ===========================================================================
# AutoBuyConfig
# ===========================================================================


def test_auto_buy_override_bypasses_env():
    with _CleanEnv(*AUTO_BUY_ENV_VARS):
        with _PatchEnv(AUTO_BUY_MIN_SCORE="13.0"):
            cfg = load_auto_buy_config(min_score=20.0)
    assert cfg.min_score == 20.0


def test_auto_buy_override_goes_through_validation():
    with _CleanEnv(*AUTO_BUY_ENV_VARS):
        exc = _raises(ValueError, load_auto_buy_config, max_orders_per_run=0)
    assert "max_orders_per_run" in str(exc)
    assert "AUTO_BUY_MAX_ORDERS_PER_RUN" in str(exc)
    assert ">= 1" in str(exc)


def test_auto_buy_negative_position_size_rejected():
    with _CleanEnv(*AUTO_BUY_ENV_VARS):
        exc = _raises(ValueError, load_auto_buy_config, position_size_pct=-0.1)
    assert "position_size_pct" in str(exc)
    assert "> 0" in str(exc)


def test_auto_buy_zero_take_profit_matches_legacy_env_parse():
    with _CleanEnv(*AUTO_BUY_ENV_VARS):
        cfg = load_auto_buy_config(take_profit_pct=0.0)
    assert cfg.take_profit_pct == 0.0


def test_auto_buy_partial_override_preserves_defaults():
    with _CleanEnv(*AUTO_BUY_ENV_VARS):
        cfg = load_auto_buy_config(max_daily_orders=5)
    assert cfg.max_daily_orders == 5
    assert cfg.max_active_positions == 8
    assert cfg.signal_mode == AutoBuyConfig.signal_mode
    assert cfg.min_score == AutoBuyConfig.min_score
    assert cfg.cooldown_minutes == AutoBuyConfig.cooldown_minutes
    assert cfg.bucking_tape_min_volume_ratio == AutoBuyConfig.bucking_tape_min_volume_ratio
    assert (
        cfg.paper_strong_evidence_score_buffer == AutoBuyConfig.paper_strong_evidence_score_buffer
    )


def test_auto_buy_no_env_dependency():
    with _CleanEnv(*AUTO_BUY_ENV_VARS):
        cfg = load_auto_buy_config()
    assert cfg.live_buys is False
    assert cfg.min_score == 13.0
    assert cfg.max_orders_per_run == 3
    assert cfg.max_active_positions == 8
    assert cfg.max_daily_orders == 30
    assert cfg.bucking_tape_min_volume_ratio == 1.8
    assert cfg.signal_mode == "legacy_source_gate"
    assert cfg.tradingview_alerts_deprecated is False
    assert cfg.paper_strong_evidence_promotion_enabled is True
    assert cfg.paper_strong_evidence_score_buffer == 3.0
    assert cfg.paper_strong_evidence_min_setup_score == 50.0
    assert cfg.paper_strong_evidence_min_ml_score == 50.0
    assert cfg.paper_strong_evidence_min_session_score == 5.0
    assert cfg.paper_exploration_fallback_enabled is True
    assert cfg.watch_setup_strong_buy_enabled is True
    assert cfg.learned_tiebreaker_min_sample_size == 10
    assert cfg.learned_tiebreaker_max_threshold_gap == 6.0
    assert cfg.layered_ml_enabled is True
    assert cfg.layered_ml_promotion_enabled is True
    assert cfg.max_symbols_per_run == 12
    assert cfg.timing_log_enabled is True
    assert cfg.score_detail_log_enabled is True


def test_auto_buy_live_runtime_defaults_match_legacy_manager():
    with _CleanEnv(*AUTO_BUY_ENV_VARS):
        with _PatchEnv(EXECUTION_MODE="live"):
            cfg = load_auto_buy_config()
    assert cfg.max_orders_per_run == 1
    assert cfg.max_active_positions == 3
    assert cfg.max_daily_orders == 12
    assert cfg.paper_strong_evidence_promotion_enabled is False
    assert cfg.paper_exploration_fallback_enabled is False
    assert cfg.watch_setup_strong_buy_enabled is False
    assert cfg.learned_tiebreaker_min_sample_size == 25
    assert cfg.learned_tiebreaker_max_threshold_gap == 4.0
    assert cfg.layered_ml_enabled is False
    assert cfg.layered_ml_promotion_enabled is False
    assert cfg.layered_ml_veto_hard_block_enabled is False


def test_auto_buy_paper_strong_evidence_env_vars_are_read():
    with _CleanEnv(*AUTO_BUY_ENV_VARS):
        with _PatchEnv(
            AUTO_BUY_PAPER_STRONG_EVIDENCE_PROMOTION_ENABLED="false",
            AUTO_BUY_PAPER_STRONG_EVIDENCE_SCORE_BUFFER="4.5",
            AUTO_BUY_PAPER_STRONG_EVIDENCE_MIN_SETUP_SCORE="60",
            AUTO_BUY_PAPER_STRONG_EVIDENCE_MIN_ML_SCORE="52",
            AUTO_BUY_PAPER_STRONG_EVIDENCE_MIN_SESSION_SCORE="6",
        ):
            cfg = load_auto_buy_config()
    assert cfg.paper_strong_evidence_promotion_enabled is False
    assert cfg.paper_strong_evidence_score_buffer == 4.5
    assert cfg.paper_strong_evidence_min_setup_score == 60.0
    assert cfg.paper_strong_evidence_min_ml_score == 52.0
    assert cfg.paper_strong_evidence_min_session_score == 6.0


def test_auto_buy_remaining_threshold_env_vars_are_read():
    with _CleanEnv(*AUTO_BUY_ENV_VARS):
        with _PatchEnv(
            AUTO_BUY_PAPER_EXPLORATION_FALLBACK_ENABLED="false",
            AUTO_BUY_PAPER_EXPLORATION_MIN_SCORE="11.5",
            AUTO_BUY_ML_WEAK_BLOCK_ENABLED="false",
            AUTO_BUY_ML_WEAK_BLOCK_SCORE="42",
            AUTO_BUY_LEARNED_TIEBREAKER_MIN_SAMPLE_SIZE="15",
            AUTO_BUY_LEARNED_TIEBREAKER_MAX_THRESHOLD_GAP="3.5",
            AUTO_BUY_LAYERED_ML_ENABLED="false",
            AUTO_BUY_LAYERED_ML_SCORE_BOOST="2.25",
            AUTO_BUY_MAX_SYMBOLS_PER_RUN="9",
            AUTO_BUY_TIMING_LOG_ENABLED="false",
            AUTO_BUY_SCORE_DETAIL_LOG_ENABLED="false",
            AUTO_BUY_EARLY_BUILD_MAX_SESSION_RETURN_PCT="0.8",
            AUTO_BUY_MATURE_CHASE_VWAP_DIST_PCT="1.2",
            AUTO_BUY_EXTREME_CHASE_BLOCK_VWAP_DIST_PCT="1.4",
        ):
            cfg = load_auto_buy_config()
    assert cfg.paper_exploration_fallback_enabled is False
    assert cfg.paper_exploration_min_score == 11.5
    assert cfg.ml_weak_block_enabled is False
    assert cfg.ml_weak_block_score == 42.0
    assert cfg.learned_tiebreaker_min_sample_size == 15
    assert cfg.learned_tiebreaker_max_threshold_gap == 3.5
    assert cfg.layered_ml_enabled is False
    assert cfg.layered_ml_score_boost == 2.25
    assert cfg.max_symbols_per_run == 9
    assert cfg.timing_log_enabled is False
    assert cfg.score_detail_log_enabled is False
    assert cfg.early_build_max_session_return_pct == 0.8
    assert cfg.mature_chase_vwap_dist_pct == 1.2
    assert cfg.extreme_chase_block_vwap_dist_pct == 1.4


def test_auto_buy_signal_mode_env_var_is_read():
    with _CleanEnv(*AUTO_BUY_ENV_VARS):
        with _PatchEnv(AUTO_BUY_SIGNAL_MODE="internal_all", TRADINGVIEW_ALERTS_DEPRECATED="true"):
            cfg = load_auto_buy_config()
    assert cfg.signal_mode == "internal_all"
    assert cfg.tradingview_alerts_deprecated is True


def test_auto_buy_invalid_signal_mode_is_rejected():
    with _CleanEnv(*AUTO_BUY_ENV_VARS):
        exc = _raises(ValueError, load_auto_buy_config, signal_mode="surprise")
    assert "AUTO_BUY_SIGNAL_MODE" in str(exc)
    assert "legacy_source_gate" in str(exc)


# ===========================================================================
# AutoSellConfig
# ===========================================================================


def test_auto_sell_override_bypasses_env():
    with _PatchEnv(POSITION_MOMENTUM_AUTO_SELL="false"):
        cfg = load_auto_sell_config(auto_sell=True)
    assert cfg.auto_sell is True


def test_auto_sell_partial_override_preserves_defaults():
    with _CleanEnv(*AUTO_SELL_ENV_VARS):
        cfg = load_auto_sell_config(emergency_loss_pct=-2.0)
    assert cfg.emergency_loss_pct == -2.0
    assert cfg.layered_ml_min_exit_confidence == (AutoSellConfig.layered_ml_min_exit_confidence)
    assert cfg.failed_high_run_loss_pct == AutoSellConfig.failed_high_run_loss_pct


def test_auto_sell_no_env_dependency_paper_defaults():
    with _CleanEnv(*AUTO_SELL_ENV_VARS):
        cfg = load_auto_sell_config()
    assert cfg.auto_sell is False
    assert cfg.layered_ml_enabled is True
    assert cfg.emergency_loss_pct == -1.25
    assert cfg.min_profit_sell_pct == 0.50


def test_auto_sell_live_runtime_default_disables_layered_ml():
    with _CleanEnv(*AUTO_SELL_ENV_VARS):
        with _PatchEnv(EXECUTION_MODE="live"):
            cfg = load_auto_sell_config()
    assert cfg.layered_ml_enabled is False


def test_auto_sell_env_vars_are_read_when_no_override():
    with _PatchEnv(
        POSITION_MOMENTUM_AUTO_SELL="true",
        POSITION_MOMENTUM_EMERGENCY_LOSS_PCT="-2.5",
        POSITION_MOMENTUM_SEVERE_BREAKDOWN_SCORE="-8",
    ):
        cfg = load_auto_sell_config()
    assert cfg.auto_sell is True
    assert cfg.emergency_loss_pct == -2.5
    assert cfg.severe_breakdown_score == -8.0


# ===========================================================================
# PositionManagerConfig
# ===========================================================================


def test_pm_override_bypasses_env():
    with _PatchEnv(POSITION_MANAGER_FULL_EXIT_LOSS_PCT="-1.25"):
        cfg = load_position_manager_config(full_exit_loss_pct=-2.0)
    assert cfg.full_exit_loss_pct == -2.0


def test_pm_positive_loss_pct_rejected():
    exc = _raises(
        ValueError,
        load_position_manager_config,
        full_exit_loss_pct=0.5,
    )
    assert "full_exit_loss_pct" in str(exc)
    assert "<= 0" in str(exc)


def test_pm_partial_sell_pct_bounds():
    exc = _raises(ValueError, load_position_manager_config, partial_sell_pct=0.0)
    assert "partial_sell_pct" in str(exc)
    exc = _raises(ValueError, load_position_manager_config, partial_sell_pct=1.1)
    assert "partial_sell_pct" in str(exc)


def test_pm_tier3_must_exceed_tier2():
    exc = _raises(
        ValueError,
        load_position_manager_config,
        tier2_peak_pct=3.0,
        tier3_peak_pct=2.0,
    )
    assert "tier3_peak_pct" in str(exc)
    assert "tier2_peak_pct" in str(exc)


def test_pm_lock_floor_must_be_below_peak():
    exc = _raises(
        ValueError,
        load_position_manager_config,
        lock_tier1_peak_pct=1.0,
        lock_tier1_floor_pct=1.5,
    )
    assert "lock_tier1_floor_pct" in str(exc)


def test_pm_partial_override_preserves_defaults():
    cfg = load_position_manager_config(vwap_loss_exit_pct=-0.50)
    assert cfg.vwap_loss_exit_pct == -0.50
    assert cfg.full_exit_loss_pct == PositionManagerConfig.full_exit_loss_pct
    assert cfg.partial_sell_pct == PositionManagerConfig.partial_sell_pct
    assert cfg.tier2_peak_pct == PositionManagerConfig.tier2_peak_pct


def test_pm_no_env_dependency():
    env_vars = [
        "POSITION_MANAGER_LIVE_SELLS",
        "POSITION_MANAGER_FULL_EXIT_LOSS_PCT",
        "POSITION_MANAGER_PARTIAL_SELL_PCT",
        "BREAKEVEN_LOCK_TRIGGER_PCT",
        "POSITION_MANAGER_PROFIT_CAPTURE_ENABLED",
    ]
    with _CleanEnv(*env_vars):
        cfg = load_position_manager_config()
    assert cfg.live_sells is False
    assert cfg.full_exit_loss_pct == -1.25
    assert cfg.partial_sell_pct == 0.50


def test_pm_extended_threshold_defaults():
    cfg = load_position_manager_config()
    assert cfg.bad_entry_containment_enabled is True
    assert cfg.bad_entry_containment_loss_pct == -0.65
    assert cfg.peak_lock_tier1_peak_pct == 0.30
    assert cfg.weak_peak_lock_tier2_floor_pct == 0.35
    assert cfg.strong_conviction_profit_giveback_trigger_pct == 70.0
    assert cfg.proactive_profit_capture_enabled is True
    assert cfg.proactive_strong_min_peak_pct == 0.45
    assert cfg.exit_pattern_profit_capture_enabled is True
    assert cfg.exit_pattern_min_adverse_signals == 2
    assert cfg.auto_buy_min_hold_minutes == 6.0
    assert cfg.auto_buy_min_hold_hard_loss_pct == -0.75


def test_pm_extended_threshold_env_vars_are_read():
    env_vars = [
        "POSITION_MANAGER_BAD_ENTRY_CONTAINMENT_ENABLED",
        "POSITION_MANAGER_BAD_ENTRY_CONTAINMENT_LOSS_PCT",
        "POSITION_MANAGER_PEAK_LOCK_TIER2_FLOOR_PCT",
        "POSITION_MANAGER_WEAK_PEAK_LOCK_TIER2_FLOOR_PCT",
        "POSITION_MANAGER_STRONG_CONVICTION_GIVEBACK_TRIGGER_PCT",
        "POSITION_MANAGER_PROACTIVE_STRONG_MIN_PEAK_PCT",
        "POSITION_MANAGER_EXIT_PATTERN_MIN_ADVERSE_SIGNALS",
        "POSITION_MANAGER_AUTO_BUY_MIN_HOLD_MINUTES",
        "POSITION_MANAGER_AUTO_BUY_MIN_HOLD_HARD_LOSS_PCT",
    ]
    with _CleanEnv(*env_vars):
        with _PatchEnv(
            POSITION_MANAGER_BAD_ENTRY_CONTAINMENT_ENABLED="false",
            POSITION_MANAGER_BAD_ENTRY_CONTAINMENT_LOSS_PCT="-0.8",
            POSITION_MANAGER_PEAK_LOCK_TIER2_FLOOR_PCT="0.33",
            POSITION_MANAGER_WEAK_PEAK_LOCK_TIER2_FLOOR_PCT="0.44",
            POSITION_MANAGER_STRONG_CONVICTION_GIVEBACK_TRIGGER_PCT="75",
            POSITION_MANAGER_PROACTIVE_STRONG_MIN_PEAK_PCT="0.55",
            POSITION_MANAGER_EXIT_PATTERN_MIN_ADVERSE_SIGNALS="3",
            POSITION_MANAGER_AUTO_BUY_MIN_HOLD_MINUTES="7",
            POSITION_MANAGER_AUTO_BUY_MIN_HOLD_HARD_LOSS_PCT="-0.9",
        ):
            cfg = load_position_manager_config()
    assert cfg.bad_entry_containment_enabled is False
    assert cfg.bad_entry_containment_loss_pct == -0.8
    assert cfg.peak_lock_tier2_floor_pct == 0.33
    assert cfg.weak_peak_lock_tier2_floor_pct == 0.44
    assert cfg.strong_conviction_profit_giveback_trigger_pct == 75.0
    assert cfg.proactive_strong_min_peak_pct == 0.55
    assert cfg.exit_pattern_min_adverse_signals == 3
    assert cfg.auto_buy_min_hold_minutes == 7.0
    assert cfg.auto_buy_min_hold_hard_loss_pct == -0.9


def test_pm_operator_flag_env_names_keep_position_manager_prefix():
    """Guard against silently renaming operator-facing env knobs.

    These two flags were historically read with the ``POSITION_MANAGER_``
    prefix. Dropping the prefix would silently ignore operator overrides in
    /etc/trading-bot.env (both default True), re-enabling position-exit
    behavior an operator had disabled. Pin the original env var names.
    """
    clean = [
        "POSITION_MANAGER_PROMOTE_UNEXECUTABLE_PARTIALS",
        "POSITION_MANAGER_CONTINUATION_EXIT_CHECK_ENABLED",
        "PROMOTE_UNEXECUTABLE_PARTIALS",
        "CONTINUATION_EXIT_CHECK_ENABLED",
    ]
    with _CleanEnv(*clean):
        with _PatchEnv(
            POSITION_MANAGER_PROMOTE_UNEXECUTABLE_PARTIALS="false",
            POSITION_MANAGER_CONTINUATION_EXIT_CHECK_ENABLED="false",
        ):
            cfg = load_position_manager_config()
    assert cfg.promote_unexecutable_partials is False
    assert cfg.continuation_exit_check_enabled is False


# ===========================================================================
# MLConfig
# ===========================================================================


def test_ml_override_bypasses_env():
    with _PatchEnv(STRATEGY_ENGINE_MODE="observe"):
        cfg = load_ml_config(strategy_engine_mode="off")
    assert cfg.strategy_engine_mode == "off"


def test_ml_bad_strategy_mode_rejected():
    exc = _raises(ValueError, load_ml_config, strategy_engine_mode="live")
    assert "strategy_engine_mode" in str(exc)
    assert "STRATEGY_ENGINE_MODE" in str(exc)


def test_ml_bad_exec_mode_rejected():
    exc = _raises(ValueError, load_ml_config, execution_policy_mode="live")
    assert "execution_policy_mode" in str(exc)
    assert "EXECUTION_POLICY_MODE" in str(exc)


def test_ml_partial_override_preserves_defaults():
    cfg = load_ml_config(ml_platform_enabled=True)
    assert cfg.ml_platform_enabled is True
    assert cfg.strategy_engine_mode == MLConfig.strategy_engine_mode
    assert cfg.execution_policy_mode == MLConfig.execution_policy_mode


def test_ml_no_env_dependency():
    env_vars = [
        "STRATEGY_ENGINE_MODE",
        "EXECUTION_POLICY_MODE",
        "ML_PLATFORM_ENABLED",
    ]
    with _CleanEnv(*env_vars):
        cfg = load_ml_config()
    assert cfg.strategy_engine_mode == "observe"
    assert cfg.execution_policy_mode == "compare"
    assert cfg.ml_platform_enabled is False


def test_ml_env_var_is_read_when_no_override():
    with _PatchEnv(ML_PLATFORM_ENABLED="true"):
        cfg = load_ml_config()
    assert cfg.ml_platform_enabled is True


# ===========================================================================
# Cross-cutting: config package exports only types and factories (no singletons)
# ===========================================================================


def test_config_package_exports_no_singletons():
    import config

    for name in (
        "signal_cfg",
        "risk_cfg",
        "auto_buy_cfg",
        "auto_sell_cfg",
        "position_manager_cfg",
        "positions_cfg",
        "ml_cfg",
    ):
        assert not hasattr(config, name), (
            f"config.{name} should not exist — singletons belong at the callsite"
        )


def test_config_package_exports_all_factories():
    from config import (  # noqa: F401
        load_auto_buy_config,
        load_auto_sell_config,
        load_ml_config,
        load_position_manager_config,
        load_positions_config,
        load_risk_config,
        load_signal_config,
    )


def test_config_package_exports_all_types():
    from config import (  # noqa: F401
        AutoBuyConfig,
        AutoSellConfig,
        MLConfig,
        PositionManagerConfig,
        PositionsConfig,
        RiskConfig,
        SignalConfig,
    )


# ===========================================================================
# Runner
# ===========================================================================


def main():
    tests = [
        # SignalConfig
        test_signal_override_bypasses_env,
        test_signal_override_goes_through_validation,
        test_signal_partial_override_preserves_defaults,
        test_signal_no_env_dependency,
        test_signal_env_var_is_read_when_no_override,
        test_signal_override_wins_over_env,
        # RiskConfig
        test_risk_override_bypasses_env,
        test_risk_override_goes_through_validation,
        test_risk_portfolio_replacement_accepts_live_rotation_mode,
        test_risk_circuit_breaker_mode_validation,
        test_risk_override_loss_pct_sign,
        test_risk_partial_override_preserves_defaults,
        test_risk_no_env_dependency,
        test_risk_circuit_breaker_env_var_is_read_when_no_override,
        # AutoBuyConfig
        test_auto_buy_override_bypasses_env,
        test_auto_buy_override_goes_through_validation,
        test_auto_buy_negative_position_size_rejected,
        test_auto_buy_zero_take_profit_matches_legacy_env_parse,
        test_auto_buy_partial_override_preserves_defaults,
        test_auto_buy_no_env_dependency,
        test_auto_buy_live_runtime_defaults_match_legacy_manager,
        test_auto_buy_paper_strong_evidence_env_vars_are_read,
        test_auto_buy_remaining_threshold_env_vars_are_read,
        test_auto_buy_signal_mode_env_var_is_read,
        test_auto_buy_invalid_signal_mode_is_rejected,
        # AutoSellConfig
        test_auto_sell_override_bypasses_env,
        test_auto_sell_partial_override_preserves_defaults,
        test_auto_sell_no_env_dependency_paper_defaults,
        test_auto_sell_live_runtime_default_disables_layered_ml,
        test_auto_sell_env_vars_are_read_when_no_override,
        # PositionManagerConfig
        test_pm_override_bypasses_env,
        test_pm_positive_loss_pct_rejected,
        test_pm_partial_sell_pct_bounds,
        test_pm_tier3_must_exceed_tier2,
        test_pm_lock_floor_must_be_below_peak,
        test_pm_partial_override_preserves_defaults,
        test_pm_no_env_dependency,
        test_pm_extended_threshold_defaults,
        test_pm_extended_threshold_env_vars_are_read,
        # MLConfig
        test_ml_override_bypasses_env,
        test_ml_bad_strategy_mode_rejected,
        test_ml_bad_exec_mode_rejected,
        test_ml_partial_override_preserves_defaults,
        test_ml_no_env_dependency,
        test_ml_env_var_is_read_when_no_override,
        # Package-level contracts
        test_config_package_exports_no_singletons,
        test_config_package_exports_all_factories,
        test_config_package_exports_all_types,
    ]

    passed = 0
    for test in tests:
        try:
            test()
            print(f"[OK] {test.__name__}")
            passed += 1
        except Exception as exc:
            print(f"[FAIL] {test.__name__}: {exc}")

    print()
    if passed == len(tests):
        print(f"All {passed} config factory tests passed.")
    else:
        print(f"{passed}/{len(tests)} passed — {len(tests) - passed} FAILED")
        sys.exit(1)


if __name__ == "__main__":
    main()
