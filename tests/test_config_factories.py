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
    raise AssertionError(
        f"Expected {exc_type.__name__} but no exception was raised"
    )


# ---------------------------------------------------------------------------
# Import factories (no singletons touched)
# ---------------------------------------------------------------------------

from config.signal import SignalConfig, load_signal_config
from config.risk import RiskConfig, load_risk_config
from config.auto_buy import AutoBuyConfig, load_auto_buy_config
from config.position_manager import PositionManagerConfig, load_position_manager_config
from config.ml import MLConfig, load_ml_config

RISK_ENV_VARS = [
    "MACRO_POSITION_COUNT_FLOOR", "PORTFOLIO_ROTATION_ENABLED",
    "PORTFOLIO_REPLACEMENT_MODE", "RISK_POLICY_MODE",
    "REGIME_CIRCUIT_BREAKER_MODE",
    "ENFORCE_SESSION_MOMENTUM_GATE", "ENFORCE_ADAPTIVE_CHURN_REENTRY",
]
AUTO_BUY_ENV_VARS = [
    "AUTO_BUY_LIVE_BUYS", "AUTO_BUY_MIN_SCORE", "AUTO_BUY_MAX_ACTIVE_POSITIONS",
    "AUTO_BUY_MAX_DAILY_ORDERS", "AUTO_BUY_COOLDOWN_MINUTES",
    "AUTO_BUY_BUCKING_TAPE_MIN_VOLUME_RATIO", "AUTO_BUY_SIGNAL_MODE",
    "TRADINGVIEW_ALERTS_DEPRECATED", "AUTO_BUY_MAX_ORDERS_PER_RUN",
    "AUTO_BUY_MAX_SIGNALS_PER_SYMBOL",
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
        "PREDICTION_GATE_MODE", "PREDICTION_SOFT_AVOID_MIN_SAMPLE_SIZE",
        "ONE_BAR_CONFIRMATION_HOLD_ENABLED", "ONE_BAR_CONFIRMATION_TIMEOUT_SECONDS",
        "TAPE_EXCEPTION_ENABLED", "OPEN_MOMENTUM_FAST_LANE_ENABLED",
        "MAX_SIGNAL_PRICE_DRIFT_PCT", "MAX_BID_ASK_SPREAD_PCT",
        "SELL_CONTINUATION_CHECK_ENABLED", "SELL_CONTINUATION_MIN_SUPPORTS",
        "WEBHOOK_SECRET", "SESSION_MAX_TRADE_COUNT", "SIGNAL_WORKER_COUNT",
        "LATE_QUOTE_DELAY_MIN_BLOCKS",
    ]
    with _CleanEnv(*env_vars):
        cfg = load_signal_config()
    assert cfg.prediction_gate_mode == "warn"
    assert cfg.session_max_trade_count == 3
    assert cfg.webhook_secret == "changeme"


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
            ValueError, load_risk_config,
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


def test_auto_buy_partial_override_preserves_defaults():
    with _CleanEnv(*AUTO_BUY_ENV_VARS):
        cfg = load_auto_buy_config(max_daily_orders=5)
    assert cfg.max_daily_orders == 5
    assert cfg.max_active_positions == AutoBuyConfig.max_active_positions
    assert cfg.signal_mode == AutoBuyConfig.signal_mode
    assert cfg.min_score == AutoBuyConfig.min_score
    assert cfg.cooldown_minutes == AutoBuyConfig.cooldown_minutes
    assert cfg.bucking_tape_min_volume_ratio == AutoBuyConfig.bucking_tape_min_volume_ratio


def test_auto_buy_no_env_dependency():
    with _CleanEnv(*AUTO_BUY_ENV_VARS):
        cfg = load_auto_buy_config()
    assert cfg.live_buys is False
    assert cfg.min_score == 13.0
    assert cfg.max_active_positions == 3
    assert cfg.max_daily_orders == 12
    assert cfg.bucking_tape_min_volume_ratio == 1.8
    assert cfg.signal_mode == "legacy_source_gate"
    assert cfg.tradingview_alerts_deprecated is False


def test_auto_buy_signal_mode_env_var_is_read():
    with _PatchEnv(AUTO_BUY_SIGNAL_MODE="internal_all", TRADINGVIEW_ALERTS_DEPRECATED="true"):
        cfg = load_auto_buy_config()
    assert cfg.signal_mode == "internal_all"
    assert cfg.tradingview_alerts_deprecated is True


def test_auto_buy_invalid_signal_mode_is_rejected():
    exc = _raises(ValueError, load_auto_buy_config, signal_mode="surprise")
    assert "AUTO_BUY_SIGNAL_MODE" in str(exc)
    assert "legacy_source_gate" in str(exc)


# ===========================================================================
# PositionManagerConfig
# ===========================================================================

def test_pm_override_bypasses_env():
    with _PatchEnv(POSITION_MANAGER_FULL_EXIT_LOSS_PCT="-1.25"):
        cfg = load_position_manager_config(full_exit_loss_pct=-2.0)
    assert cfg.full_exit_loss_pct == -2.0


def test_pm_positive_loss_pct_rejected():
    exc = _raises(
        ValueError, load_position_manager_config,
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
        ValueError, load_position_manager_config,
        tier2_peak_pct=3.0, tier3_peak_pct=2.0,
    )
    assert "tier3_peak_pct" in str(exc)
    assert "tier2_peak_pct" in str(exc)


def test_pm_lock_floor_must_be_below_peak():
    exc = _raises(
        ValueError, load_position_manager_config,
        lock_tier1_peak_pct=1.0, lock_tier1_floor_pct=1.5,
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
        "POSITION_MANAGER_LIVE_SELLS", "POSITION_MANAGER_FULL_EXIT_LOSS_PCT",
        "POSITION_MANAGER_PARTIAL_SELL_PCT", "BREAKEVEN_LOCK_TRIGGER_PCT",
        "POSITION_MANAGER_PROFIT_CAPTURE_ENABLED",
    ]
    with _CleanEnv(*env_vars):
        cfg = load_position_manager_config()
    assert cfg.live_sells is False
    assert cfg.full_exit_loss_pct == -1.25
    assert cfg.partial_sell_pct == 0.50


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
        "STRATEGY_ENGINE_MODE", "EXECUTION_POLICY_MODE", "ML_PLATFORM_ENABLED",
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
    for name in ("signal_cfg", "risk_cfg", "auto_buy_cfg", "position_manager_cfg", "ml_cfg"):
        assert not hasattr(config, name), (
            f"config.{name} should not exist — singletons belong at the callsite"
        )


def test_config_package_exports_all_factories():
    from config import (  # noqa: F401
        load_signal_config,
        load_risk_config,
        load_auto_buy_config,
        load_position_manager_config,
        load_ml_config,
    )


def test_config_package_exports_all_types():
    from config import (  # noqa: F401
        SignalConfig,
        RiskConfig,
        AutoBuyConfig,
        PositionManagerConfig,
        MLConfig,
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
        test_risk_circuit_breaker_mode_validation,
        test_risk_override_loss_pct_sign,
        test_risk_partial_override_preserves_defaults,
        test_risk_no_env_dependency,
        test_risk_circuit_breaker_env_var_is_read_when_no_override,
        # AutoBuyConfig
        test_auto_buy_override_bypasses_env,
        test_auto_buy_override_goes_through_validation,
        test_auto_buy_negative_position_size_rejected,
        test_auto_buy_partial_override_preserves_defaults,
        test_auto_buy_no_env_dependency,
        test_auto_buy_signal_mode_env_var_is_read,
        test_auto_buy_invalid_signal_mode_is_rejected,
        # PositionManagerConfig
        test_pm_override_bypasses_env,
        test_pm_positive_loss_pct_rejected,
        test_pm_partial_sell_pct_bounds,
        test_pm_tier3_must_exceed_tier2,
        test_pm_lock_floor_must_be_below_peak,
        test_pm_partial_override_preserves_defaults,
        test_pm_no_env_dependency,
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
