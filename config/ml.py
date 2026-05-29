"""ML/strategy platform configuration."""

from __future__ import annotations

from dataclasses import dataclass

from config._env import _check, env_bool, env_str

_VALID_STRATEGY_MODES = {"observe", "active", "off"}
_VALID_EXEC_MODES = {"off", "compare"}


@dataclass(frozen=True)
class MLConfig:
    # Strategy engine (observe-only until validated)
    strategy_engine_mode: str = "observe"

    # Execution policy mode for broker comparison
    execution_policy_mode: str = "compare"

    # ML dataset/training platform gate
    ml_platform_enabled: bool = False

    def __post_init__(self) -> None:
        _check(
            self.strategy_engine_mode in _VALID_STRATEGY_MODES,
            "strategy_engine_mode", "STRATEGY_ENGINE_MODE",
            self.strategy_engine_mode,
            f"must be one of {sorted(_VALID_STRATEGY_MODES)}",
        )
        _check(
            self.execution_policy_mode in _VALID_EXEC_MODES,
            "execution_policy_mode", "EXECUTION_POLICY_MODE",
            self.execution_policy_mode,
            f"must be one of {sorted(_VALID_EXEC_MODES)}",
        )


def load_ml_config(**overrides) -> MLConfig:
    """Construct MLConfig from current env, with optional kwarg overrides.

    Production code uses the ``ml_cfg`` singleton from ``config``.
    Tests call this factory directly after patching env (or pass overrides)
    to get a fresh instance without touching the singleton.

    Example::

        cfg = load_ml_config(ml_platform_enabled=True)
    """
    kwargs: dict = dict(
        strategy_engine_mode=env_str("STRATEGY_ENGINE_MODE", "observe").lower(),
        execution_policy_mode=env_str("EXECUTION_POLICY_MODE", "compare").lower(),
        ml_platform_enabled=env_bool("ML_PLATFORM_ENABLED", False),
    )
    kwargs.update(overrides)
    return MLConfig(**kwargs)
