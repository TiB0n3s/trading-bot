"""Runtime compatibility settings for the Flask signal entrypoint."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from trading_bot.config.authority_modes import (
    authority_mode_to_legacy_prediction_gate,
    normalize_config_authority_mode,
)

EnvGet = Callable[[str, str | None], str | None]
Warn = Callable[[str], None]


def _env_bool(env_get: EnvGet, name: str, default: bool) -> bool:
    raw = env_get(name, None)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_int(env_get: EnvGet, name: str, default: int) -> int:
    try:
        return int(env_get(name, str(default)) or default)
    except Exception:
        return default


def _env_float(env_get: EnvGet, name: str, default: float) -> float:
    try:
        return float(env_get(name, str(default)) or default)
    except Exception:
        return default


def _env_str(env_get: EnvGet, name: str, default: str) -> str:
    return (env_get(name, default) or default).strip()


@dataclass(frozen=True)
class RuntimeSettings:
    IS_PAPER_MODE: bool
    ENFORCE_SETUP_POLICY_BLOCKS: bool
    SIGNAL_TTL_SECONDS: int
    PREDICTION_GATE_MODE: str
    PREDICTION_GATE_AUTHORITY_MODE: str
    PREDICTION_SOFT_AVOID_MIN_SAMPLE_SIZE: int
    INTRA_SESSION_TAPE_DEGRADATION_ENABLED: bool
    INTRA_SESSION_TAPE_DEGRADATION_START_HOUR_ET: int
    INTRA_SESSION_TAPE_DEGRADATION_MIN_SETUP_SCORE: float
    ONE_BAR_CONFIRMATION_HOLD_ENABLED: bool
    ONE_BAR_CONFIRMATION_EXTENSION_THRESHOLD_PCT: float
    ONE_BAR_CONFIRMATION_TIMEOUT_SECONDS: int
    TAPE_EXCEPTION_ENABLED: bool
    OPEN_MOMENTUM_FAST_LANE_ENABLED: bool
    MACRO_POSITION_COUNT_FLOOR: float
    MACRO_DUST_POSITION_ALLOWANCE: int
    ENFORCE_PREDICTION_BLOCKS: bool
    ENFORCE_PREDICTION_WATCH_IN_CASH: bool
    STRATEGY_ENGINE_MODE: str
    RISK_POLICY_MODE: str
    ENFORCE_SESSION_MOMENTUM_GATE: bool
    ENFORCE_ADAPTIVE_CHURN_REENTRY: bool
    SIGNAL_WORKER_COUNT: int
    RECENT_FAVORABLE_SETUP_TTL_MINUTES: int


def load_runtime_settings(
    *,
    env_get: EnvGet,
    execution_mode: str,
    warn: Warn,
) -> RuntimeSettings:
    """Load runtime settings while preserving current app.py defaults."""
    prediction_gate_authority_mode = normalize_config_authority_mode(
        _env_str(env_get, "PREDICTION_GATE_MODE", "warn"),
        default="warn",
    )
    prediction_gate_mode = authority_mode_to_legacy_prediction_gate(prediction_gate_authority_mode)
    if prediction_gate_authority_mode not in (
        "off",
        "observe",
        "warn",
        "size_down",
        "paper_block",
        "live_block",
    ):
        warn(f"Invalid PREDICTION_GATE_MODE={prediction_gate_mode!r}; defaulting to warn")
        prediction_gate_authority_mode = "warn"
        prediction_gate_mode = "warn"

    strategy_engine_mode = _env_str(env_get, "STRATEGY_ENGINE_MODE", "observe").lower()
    if strategy_engine_mode not in ("off", "observe"):
        warn(f"Invalid STRATEGY_ENGINE_MODE={strategy_engine_mode!r}; defaulting to observe")
        strategy_engine_mode = "observe"

    risk_policy_mode = _env_str(env_get, "RISK_POLICY_MODE", "compare").lower()
    if risk_policy_mode not in ("off", "compare"):
        warn(f"Invalid RISK_POLICY_MODE={risk_policy_mode!r}; defaulting to compare")
        risk_policy_mode = "compare"

    return RuntimeSettings(
        # dry_run is paper-equivalent everywhere else in the system; keep this flag
        # consistent so a dry_run process is not misclassified as non-paper.
        IS_PAPER_MODE=execution_mode in {"paper", "dry_run"},
        ENFORCE_SETUP_POLICY_BLOCKS=True,
        SIGNAL_TTL_SECONDS=_env_int(env_get, "SIGNAL_TTL_SECONDS", 300),
        PREDICTION_GATE_MODE=prediction_gate_mode,
        PREDICTION_GATE_AUTHORITY_MODE=prediction_gate_authority_mode,
        PREDICTION_SOFT_AVOID_MIN_SAMPLE_SIZE=_env_int(
            env_get,
            "PREDICTION_SOFT_AVOID_MIN_SAMPLE_SIZE",
            20,
        ),
        INTRA_SESSION_TAPE_DEGRADATION_ENABLED=_env_bool(
            env_get,
            "INTRA_SESSION_TAPE_DEGRADATION_ENABLED",
            True,
        ),
        INTRA_SESSION_TAPE_DEGRADATION_START_HOUR_ET=_env_int(
            env_get,
            "INTRA_SESSION_TAPE_DEGRADATION_START_HOUR_ET",
            12,
        ),
        INTRA_SESSION_TAPE_DEGRADATION_MIN_SETUP_SCORE=_env_float(
            env_get,
            "INTRA_SESSION_TAPE_DEGRADATION_MIN_SETUP_SCORE",
            55.0,
        ),
        ONE_BAR_CONFIRMATION_HOLD_ENABLED=_env_bool(
            env_get,
            "ONE_BAR_CONFIRMATION_HOLD_ENABLED",
            True,
        ),
        ONE_BAR_CONFIRMATION_EXTENSION_THRESHOLD_PCT=_env_float(
            env_get,
            "ONE_BAR_CONFIRMATION_EXTENSION_THRESHOLD_PCT",
            0.25,
        ),
        ONE_BAR_CONFIRMATION_TIMEOUT_SECONDS=_env_int(
            env_get,
            "ONE_BAR_CONFIRMATION_TIMEOUT_SECONDS",
            75,
        ),
        TAPE_EXCEPTION_ENABLED=_env_bool(env_get, "TAPE_EXCEPTION_ENABLED", True),
        OPEN_MOMENTUM_FAST_LANE_ENABLED=_env_bool(
            env_get,
            "OPEN_MOMENTUM_FAST_LANE_ENABLED",
            True,
        ),
        MACRO_POSITION_COUNT_FLOOR=_env_float(
            env_get,
            "MACRO_POSITION_COUNT_FLOOR",
            500.0,
        ),
        MACRO_DUST_POSITION_ALLOWANCE=_env_int(
            env_get,
            "MACRO_DUST_POSITION_ALLOWANCE",
            4,
        ),
        ENFORCE_PREDICTION_BLOCKS=prediction_gate_mode == "hard",
        ENFORCE_PREDICTION_WATCH_IN_CASH=prediction_gate_mode == "hard",
        STRATEGY_ENGINE_MODE=strategy_engine_mode,
        RISK_POLICY_MODE=risk_policy_mode,
        ENFORCE_SESSION_MOMENTUM_GATE=_env_bool(
            env_get,
            "ENFORCE_SESSION_MOMENTUM_GATE",
            False,
        ),
        ENFORCE_ADAPTIVE_CHURN_REENTRY=_env_bool(
            env_get,
            "ENFORCE_ADAPTIVE_CHURN_REENTRY",
            True,
        ),
        SIGNAL_WORKER_COUNT=_env_int(env_get, "SIGNAL_WORKER_COUNT", 3),
        RECENT_FAVORABLE_SETUP_TTL_MINUTES=15,
    )
