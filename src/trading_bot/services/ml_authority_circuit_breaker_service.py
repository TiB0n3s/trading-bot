"""Persistent circuit breaker for ML authority degradation."""

from __future__ import annotations

import json
import os
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_ML_AUTHORITY_CIRCUIT_PATH = Path("runtime_state/ml_authority_circuit_breaker.json")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _parse_dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except Exception:
        return None


def _bool(value: Any, default: bool = False) -> bool:
    if value is None:
        return default
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


@dataclass(frozen=True)
class MLAuthorityCircuitState:
    version: str
    state: str
    consecutive_failures: int
    threshold: int
    opened_at: str | None
    open_until: str | None
    last_failure_reason: str | None
    updated_at: str

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class MLAuthorityCircuitBreaker:
    """Small file-backed circuit breaker for authority model health.

    The breaker intentionally degrades only ML authority. It does not alter
    deterministic risk gates, execution quality gates, or lockout interceptors.
    """

    def __init__(
        self,
        *,
        path: Path | str = DEFAULT_ML_AUTHORITY_CIRCUIT_PATH,
        threshold: int = 5,
        recovery_seconds: int = 1800,
    ):
        self.path = Path(path)
        self.threshold = max(1, int(threshold))
        self.recovery_seconds = max(1, int(recovery_seconds))

    def read(self) -> MLAuthorityCircuitState:
        if self.path.exists():
            try:
                payload = json.loads(self.path.read_text())
                return MLAuthorityCircuitState(
                    version=str(payload.get("version") or "ml_authority_circuit_v1"),
                    state=str(payload.get("state") or "closed"),
                    consecutive_failures=int(payload.get("consecutive_failures") or 0),
                    threshold=int(payload.get("threshold") or self.threshold),
                    opened_at=payload.get("opened_at"),
                    open_until=payload.get("open_until"),
                    last_failure_reason=payload.get("last_failure_reason"),
                    updated_at=str(payload.get("updated_at") or _now().isoformat()),
                )
            except Exception:
                pass
        return MLAuthorityCircuitState(
            version="ml_authority_circuit_v1",
            state="closed",
            consecutive_failures=0,
            threshold=self.threshold,
            opened_at=None,
            open_until=None,
            last_failure_reason=None,
            updated_at=_now().isoformat(),
        )

    def record(self, *, failure: bool, reason: str | None = None) -> MLAuthorityCircuitState:
        current = self.read()
        now = _now()
        open_until = _parse_dt(current.open_until)
        if current.state == "open" and open_until is not None and now < open_until:
            return current

        if not failure:
            state = MLAuthorityCircuitState(
                version="ml_authority_circuit_v1",
                state="closed",
                consecutive_failures=0,
                threshold=self.threshold,
                opened_at=None,
                open_until=None,
                last_failure_reason=None,
                updated_at=now.isoformat(),
            )
            self._write(state)
            return state

        failures = int(current.consecutive_failures or 0) + 1
        opened = failures >= self.threshold
        state = MLAuthorityCircuitState(
            version="ml_authority_circuit_v1",
            state="open" if opened else "closed",
            consecutive_failures=failures,
            threshold=self.threshold,
            opened_at=now.isoformat() if opened else None,
            open_until=(now + timedelta(seconds=self.recovery_seconds)).isoformat()
            if opened
            else None,
            last_failure_reason=reason or "ml authority prediction failure",
            updated_at=now.isoformat(),
        )
        self._write(state)
        return state

    def _write(self, state: MLAuthorityCircuitState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(self.path.suffix + ".tmp")
        tmp.write_text(json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n")
        tmp.replace(self.path)


def circuit_config_from(
    config: dict[str, Any],
    *,
    env: dict[str, str] | None = None,
) -> dict[str, Any]:
    env = dict(os.environ if env is None else env)
    raw = config.get("circuit_breaker")
    raw = raw if isinstance(raw, dict) else {}
    enabled = _bool(
        raw.get("enabled", env.get("ML_AUTHORITY_CIRCUIT_BREAKER_ENABLED")),
        default=True,
    )
    return {
        "enabled": enabled,
        "threshold": int(
            raw.get("threshold") or env.get("ML_AUTHORITY_CIRCUIT_FAILURE_THRESHOLD") or 5
        ),
        "recovery_seconds": int(
            raw.get("recovery_seconds") or env.get("ML_AUTHORITY_CIRCUIT_RECOVERY_SECONDS") or 1800
        ),
        "path": raw.get("path")
        or env.get("ML_AUTHORITY_CIRCUIT_PATH")
        or str(DEFAULT_ML_AUTHORITY_CIRCUIT_PATH),
        "open_mode": str(
            raw.get("open_mode")
            or env.get("ML_AUTHORITY_CIRCUIT_OPEN_MODE")
            or "observe_only_compare"
        )
        .strip()
        .lower(),
    }
