"""Shared env-var helpers used by all config dataclasses."""

from __future__ import annotations

import os


def _check(condition: bool, field: str, env_var: str, value, constraint: str) -> None:
    """Raise ValueError with a uniform, operator-friendly message when a config value is invalid.

    Args:
        condition:  The invariant that must be True.
        field:      Python field name (e.g. ``"macro_position_count_floor"``).
        env_var:    Corresponding env var (e.g. ``"MACRO_POSITION_COUNT_FLOOR"``).
        value:      The received value (shown in the error so the operator knows what to fix).
        constraint: Human-readable description (e.g. ``"must be >= 0"``).
    """
    if not condition:
        raise ValueError(
            f"{field} (env var {env_var}) {constraint}; got {value!r}"
        )


def env_bool(name: str, default: bool = False) -> bool:
    raw = os.getenv(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def env_int(name: str, default: int) -> int:
    try:
        return int(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except (TypeError, ValueError):
        return default


def env_str(name: str, default: str) -> str:
    return os.getenv(name, default).strip()


def env_str_set(name: str, default: str) -> frozenset[str]:
    raw = os.getenv(name, default)
    return frozenset(s.strip().upper() for s in raw.split(",") if s.strip())


def env_str_lower_set(name: str, default: str) -> frozenset[str]:
    raw = os.getenv(name, default)
    return frozenset(s.strip().lower() for s in raw.split(",") if s.strip())
