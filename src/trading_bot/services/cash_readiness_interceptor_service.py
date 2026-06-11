"""Cash-readiness execution interceptor.

This gate sits at the execution boundary and blocks broker submission when
cash-mode prerequisites are not satisfied. It intentionally depends only on
persistent state and lightweight status payloads.
"""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from services.persistent_lockout_service import PersistentLockoutService

CASH_EXECUTION_MODES = {"cash_safe", "cash_full"}
DEFAULT_LOCKOUT_PATH = Path("runtime_state") / "risk_lockout.json"


@dataclass(frozen=True)
class CashReadinessDecision:
    allowed: bool
    reason: str | None = None
    category: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "allowed": self.allowed,
            "reason": self.reason,
            "category": self.category,
            "metadata": self.metadata,
        }


def _lockout_path() -> Path:
    configured = os.getenv("RISK_LOCKOUT_STATE_PATH")
    return Path(configured) if configured else DEFAULT_LOCKOUT_PATH


def _cash_mode(execution_mode: str) -> bool:
    return str(execution_mode or "").strip().lower() in CASH_EXECUTION_MODES


def _prediction_status_from_runtime(account_state: dict[str, Any]) -> dict[str, Any] | None:
    for key in ("prediction_cache_status", "ml_prediction_cache"):
        value = account_state.get(key)
        if isinstance(value, dict):
            return value
    try:
        from prediction_cache import prediction_cache_status  # noqa: PLC0415

        status = prediction_cache_status()
        return status if isinstance(status, dict) else None
    except Exception as exc:
        return {"available": False, "last_error": str(exc)}


def _prediction_status_is_invalid(status: dict[str, Any] | None) -> str | None:
    if not status:
        return "prediction_cache_status_missing"
    if status.get("last_error"):
        return f"prediction_cache_error:{status.get('last_error')}"
    if status.get("stale") is True:
        return "prediction_cache_stale"
    if not status.get("market_date"):
        return "prediction_cache_market_date_missing"
    if int(status.get("symbol_count") or 0) <= 0:
        return "prediction_cache_empty"
    return None


def evaluate_cash_readiness_interceptor(
    *,
    action: str,
    execution_mode: str,
    account_state: dict[str, Any],
    lockout_service: PersistentLockoutService | None = None,
) -> CashReadinessDecision:
    """Return whether order routing may continue.

    Persistent lockout always blocks non-dry-run broker submission. Prediction
    cache freshness is enforced for cash modes only unless explicitly requested
    for paper validation.
    """
    mode = str(execution_mode or "").strip().lower()
    lockout_service = lockout_service or PersistentLockoutService(_lockout_path())
    lockout_state = lockout_service.read()
    if lockout_state.active:
        return CashReadinessDecision(
            allowed=False,
            category="persistent_risk_lockout",
            reason=f"{lockout_state.status}: {lockout_state.reason}",
            metadata={"lockout_state": lockout_state.to_dict()},
        )

    enforce_prediction_cache = _cash_mode(mode) or os.getenv(
        "PREDICTION_CACHE_CASH_LOCKOUT_IN_PAPER", "false"
    ).strip().lower() in {"1", "true", "yes", "on"}
    if action.lower() == "buy" and enforce_prediction_cache:
        status = _prediction_status_from_runtime(account_state)
        invalid_reason = _prediction_status_is_invalid(status)
        if invalid_reason:
            state = lockout_service.activate(
                reason=f"cash_prediction_cache_gate:{invalid_reason}",
                payload={
                    "execution_mode": mode,
                    "action": action,
                    "prediction_cache_status": status or {},
                    "runtime_effect": "cash_freeze_until_prediction_cache_refreshed",
                },
            )
            return CashReadinessDecision(
                allowed=False,
                category="prediction_cache_cash_freeze",
                reason=f"cash prediction cache gate failed: {invalid_reason}",
                metadata={
                    "prediction_cache_status": status or {},
                    "lockout_state": state.to_dict(),
                },
            )

    return CashReadinessDecision(
        allowed=True,
        metadata={"execution_mode": mode, "prediction_cache_checked": enforce_prediction_cache},
    )
