"""Persistent file-backed risk lockout state."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

LOCKOUT_STATE_VERSION = "risk_lockout_state_v1"


@dataclass(frozen=True)
class LockoutState:
    version: str
    active: bool
    status: str
    reason: str | None
    updated_at: str | None
    payload: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class PersistentLockoutService:
    def __init__(self, path: Path | str):
        self.path = Path(path)

    def read(self) -> LockoutState:
        if not self.path.exists():
            return LockoutState(
                version=LOCKOUT_STATE_VERSION,
                active=False,
                status="normal",
                reason=None,
                updated_at=None,
                payload={},
            )
        try:
            data = json.loads(self.path.read_text())
            if not isinstance(data, dict):
                raise ValueError("lockout file did not contain an object")
        except Exception as exc:
            return LockoutState(
                version=LOCKOUT_STATE_VERSION,
                active=True,
                status="lockout_parse_error",
                reason=str(exc),
                updated_at=None,
                payload={},
            )
        return LockoutState(
            version=str(data.get("version") or LOCKOUT_STATE_VERSION),
            active=bool(data.get("active")),
            status=str(data.get("status") or ("lockout" if data.get("active") else "normal")),
            reason=data.get("reason"),
            updated_at=data.get("updated_at"),
            payload=data.get("payload") if isinstance(data.get("payload"), dict) else {},
        )

    def activate(self, *, reason: str, payload: dict[str, Any] | None = None) -> LockoutState:
        state = LockoutState(
            version=LOCKOUT_STATE_VERSION,
            active=True,
            status="lockout",
            reason=reason,
            updated_at=_now(),
            payload=payload or {},
        )
        self._write(state)
        return state

    def set_rebuilding(self, *, reason: str, payload: dict[str, Any] | None = None) -> LockoutState:
        state = LockoutState(
            version=LOCKOUT_STATE_VERSION,
            active=True,
            status="rebuilding",
            reason=reason,
            updated_at=_now(),
            payload=payload or {},
        )
        self._write(state)
        return state

    def clear(self, *, reason: str = "manual_clear") -> LockoutState:
        state = LockoutState(
            version=LOCKOUT_STATE_VERSION,
            active=False,
            status="normal",
            reason=reason,
            updated_at=_now(),
            payload={},
        )
        self._write(state)
        return state

    def _write(self, state: LockoutState) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_name(f".{self.path.name}.tmp")
        tmp.write_text(json.dumps(state.to_dict(), indent=2, sort_keys=True) + "\n")
        tmp.replace(self.path)
