"""Risk and position-sizing configuration (app.py macro/portfolio gates)."""

from __future__ import annotations

from dataclasses import dataclass, field

from config._env import (
    _check,
    env_bool,
    env_float,
    env_int,
    env_str,
    env_str_lower_set,
    env_str_set,
)

_VALID_REPLACEMENT_MODES = {"observe_only", "active", "live_rotation", "off"}
_VALID_RISK_POLICY_MODES = {"off", "compare"}
_VALID_CIRCUIT_BREAKER_MODES = {"off", "observe", "warn", "block"}


@dataclass(frozen=True)
class RiskConfig:
    # Macro position count gate
    macro_position_count_floor: float = 500.0

    # Portfolio rotation
    portfolio_rotation_enabled: bool = False
    portfolio_rotation_min_candidate_score: int = 12
    portfolio_rotation_max_per_day: int = 2
    portfolio_rotation_min_hold_minutes: int = 30
    portfolio_rotation_max_weak_plpc: float = 0.0
    portfolio_rotation_excluded_symbols: frozenset[str] = field(
        default_factory=lambda: frozenset({"SPY", "QQQ", "GLD", "IWM"})
    )
    portfolio_rotation_allowed_risk_levels: frozenset[str] = field(
        default_factory=lambda: frozenset({"low", "medium"})
    )
    portfolio_rotation_allowed_entry_qualities: frozenset[str] = field(
        default_factory=lambda: frozenset({"excellent", "high", "good_on_pullbacks"})
    )

    # Portfolio replacement (separate from rotation)
    portfolio_replacement_mode: str = "observe_only"
    portfolio_replacement_live_sells: bool = False
    portfolio_replacement_require_replace_now: bool = False
    portfolio_replacement_min_candidate_score: float = 120.0
    portfolio_replacement_min_buy_score: float = 15.0
    portfolio_replacement_weak_holding_plpc: float = -1.00

    # Risk policy mode
    risk_policy_mode: str = "compare"

    # Regime circuit breaker enforcement mode
    # off=no effect (default); observe=log only; warn=annotate; block=reject buys
    regime_circuit_breaker_mode: str = "off"

    # Misc signal-level risk gates
    enforce_session_momentum_gate: bool = True
    enforce_adaptive_churn_reentry: bool = True

    def __post_init__(self) -> None:
        _check(
            self.macro_position_count_floor >= 0,
            "macro_position_count_floor",
            "MACRO_POSITION_COUNT_FLOOR",
            self.macro_position_count_floor,
            "must be >= 0",
        )
        _check(
            self.portfolio_rotation_min_candidate_score >= 1,
            "portfolio_rotation_min_candidate_score",
            "PORTFOLIO_ROTATION_MIN_CANDIDATE_SCORE",
            self.portfolio_rotation_min_candidate_score,
            "must be >= 1",
        )
        _check(
            self.portfolio_rotation_max_per_day >= 1,
            "portfolio_rotation_max_per_day",
            "PORTFOLIO_ROTATION_MAX_PER_DAY",
            self.portfolio_rotation_max_per_day,
            "must be >= 1",
        )
        _check(
            self.portfolio_rotation_min_hold_minutes >= 1,
            "portfolio_rotation_min_hold_minutes",
            "PORTFOLIO_ROTATION_MIN_HOLD_MINUTES",
            self.portfolio_rotation_min_hold_minutes,
            "must be >= 1",
        )
        _check(
            self.portfolio_replacement_mode in _VALID_REPLACEMENT_MODES,
            "portfolio_replacement_mode",
            "PORTFOLIO_REPLACEMENT_MODE",
            self.portfolio_replacement_mode,
            f"must be one of {sorted(_VALID_REPLACEMENT_MODES)}",
        )
        _check(
            self.portfolio_replacement_min_candidate_score >= 0,
            "portfolio_replacement_min_candidate_score",
            "PORTFOLIO_REPLACEMENT_MIN_CANDIDATE_SCORE",
            self.portfolio_replacement_min_candidate_score,
            "must be >= 0",
        )
        _check(
            self.portfolio_replacement_min_buy_score >= 0,
            "portfolio_replacement_min_buy_score",
            "PORTFOLIO_REPLACEMENT_MIN_BUY_SCORE",
            self.portfolio_replacement_min_buy_score,
            "must be >= 0",
        )
        _check(
            self.portfolio_replacement_weak_holding_plpc <= 0,
            "portfolio_replacement_weak_holding_plpc",
            "PORTFOLIO_REPLACEMENT_WEAK_HOLDING_PLPC",
            self.portfolio_replacement_weak_holding_plpc,
            "must be <= 0",
        )
        _check(
            self.risk_policy_mode in _VALID_RISK_POLICY_MODES,
            "risk_policy_mode",
            "RISK_POLICY_MODE",
            self.risk_policy_mode,
            f"must be one of {sorted(_VALID_RISK_POLICY_MODES)}",
        )
        _check(
            self.regime_circuit_breaker_mode in _VALID_CIRCUIT_BREAKER_MODES,
            "regime_circuit_breaker_mode",
            "REGIME_CIRCUIT_BREAKER_MODE",
            self.regime_circuit_breaker_mode,
            f"must be one of {sorted(_VALID_CIRCUIT_BREAKER_MODES)}",
        )


def load_risk_config(**overrides) -> RiskConfig:
    """Construct RiskConfig from current env, with optional kwarg overrides.

    Production code uses the ``risk_cfg`` singleton from ``config``.
    Tests call this factory directly after patching env (or pass overrides)
    to get a fresh instance without touching the singleton.

    Example::

        cfg = load_risk_config(portfolio_rotation_enabled=True)
    """
    kwargs: dict = dict(
        macro_position_count_floor=env_float("MACRO_POSITION_COUNT_FLOOR", 500.0),
        portfolio_rotation_enabled=env_bool("PORTFOLIO_ROTATION_ENABLED", False),
        portfolio_rotation_min_candidate_score=env_int(
            "PORTFOLIO_ROTATION_MIN_CANDIDATE_SCORE", 12
        ),
        portfolio_rotation_max_per_day=env_int("PORTFOLIO_ROTATION_MAX_PER_DAY", 2),
        portfolio_rotation_min_hold_minutes=env_int("PORTFOLIO_ROTATION_MIN_HOLD_MINUTES", 30),
        portfolio_rotation_max_weak_plpc=env_float("PORTFOLIO_ROTATION_MAX_WEAK_PLPC", 0.0),
        portfolio_rotation_excluded_symbols=env_str_set(
            "PORTFOLIO_ROTATION_EXCLUDED_SYMBOLS", "SPY,QQQ,GLD,IWM"
        ),
        portfolio_rotation_allowed_risk_levels=env_str_lower_set(
            "PORTFOLIO_ROTATION_ALLOWED_RISK_LEVELS", "low,medium"
        ),
        portfolio_rotation_allowed_entry_qualities=env_str_lower_set(
            "PORTFOLIO_ROTATION_ALLOWED_ENTRY_QUALITIES",
            "excellent,high,good_on_pullbacks",
        ),
        portfolio_replacement_mode=env_str("PORTFOLIO_REPLACEMENT_MODE", "observe_only").lower(),
        portfolio_replacement_live_sells=env_bool("PORTFOLIO_REPLACEMENT_LIVE_SELLS", False),
        portfolio_replacement_require_replace_now=env_bool(
            "PORTFOLIO_REPLACEMENT_REQUIRE_REPLACE_NOW", False
        ),
        portfolio_replacement_min_candidate_score=env_float(
            "PORTFOLIO_REPLACEMENT_MIN_CANDIDATE_SCORE", 120.0
        ),
        portfolio_replacement_min_buy_score=env_float("PORTFOLIO_REPLACEMENT_MIN_BUY_SCORE", 15.0),
        portfolio_replacement_weak_holding_plpc=env_float(
            "PORTFOLIO_REPLACEMENT_WEAK_HOLDING_PLPC", -1.00
        ),
        risk_policy_mode=env_str("RISK_POLICY_MODE", "compare").lower(),
        regime_circuit_breaker_mode=env_str("REGIME_CIRCUIT_BREAKER_MODE", "off").lower(),
        enforce_session_momentum_gate=env_bool("ENFORCE_SESSION_MOMENTUM_GATE", True),
        enforce_adaptive_churn_reentry=env_bool("ENFORCE_ADAPTIVE_CHURN_REENTRY", True),
    )
    kwargs.update(overrides)
    return RiskConfig(**kwargs)
