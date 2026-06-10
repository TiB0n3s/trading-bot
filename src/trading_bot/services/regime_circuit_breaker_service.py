"""Regime-driven circuit breaker gate.

Reads the persistent lockout state and emits a decision about whether to
allow, warn, or block a new buy based on the active regime lockout.

Enforcement mode is controlled by the ``REGIME_CIRCUIT_BREAKER_MODE`` env var
(loaded through ``config/risk.py``):

  off      - pass-through with no effect (default)
  observe  - logs what would happen; orders still flow
  warn     - annotates the decision metadata; orders still flow
  block    - blocks new buy orders when lockout is active

Sell signals always pass through regardless of mode so the bot can always
reduce exposure.

This module does NOT cancel orders, liquidate positions, or call the broker.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from services.persistent_lockout_service import LockoutState

CIRCUIT_BREAKER_VERSION = "regime_circuit_breaker_v1"
VALID_MODES = frozenset({"off", "observe", "warn", "block"})


@dataclass(frozen=True)
class CircuitBreakerDecision:
    version: str
    mode: str
    action: str  # "allow" | "warn" | "block"
    lockout_active: bool
    lockout_status: str
    lockout_reason: str | None
    runtime_effect: str
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def check_circuit_breaker(
    *,
    signal_action: str,
    lockout_state: LockoutState,
    mode: str = "off",
) -> CircuitBreakerDecision:
    """Evaluate whether to allow, warn, or block based on lockout state.

    Parameters
    ----------
    signal_action : str
        The incoming signal action string (e.g. ``"buy"`` or ``"sell"``).
    lockout_state : LockoutState
        Current persistent lockout state (from ``PersistentLockoutService``).
    mode : str
        One of ``off``, ``observe``, ``warn``, ``block``.
        Unknown values default to ``off``.
    """
    action = str(signal_action or "").strip().lower()
    mode = str(mode or "off").strip().lower()
    if mode not in VALID_MODES:
        mode = "off"

    reasons = [
        f"mode={mode}",
        f"signal_action={action}",
        f"lockout_active={lockout_state.active}",
        f"lockout_status={lockout_state.status}",
    ]

    # Sells always flow; reducing exposure must never be blocked.
    if action != "buy" or mode == "off":
        tag = "sell_exempt" if action != "buy" else "circuit_breaker_off"
        return CircuitBreakerDecision(
            version=CIRCUIT_BREAKER_VERSION,
            mode=mode,
            action="allow",
            lockout_active=lockout_state.active,
            lockout_status=lockout_state.status,
            lockout_reason=lockout_state.reason,
            runtime_effect="no_effect_pass_through",
            reasons=reasons + [tag],
        )

    if not lockout_state.active:
        return CircuitBreakerDecision(
            version=CIRCUIT_BREAKER_VERSION,
            mode=mode,
            action="allow",
            lockout_active=False,
            lockout_status=lockout_state.status,
            lockout_reason=lockout_state.reason,
            runtime_effect="no_lockout_active",
            reasons=reasons + ["lockout_not_active"],
        )

    # Lockout is active and we're in the buy path.
    if mode == "observe":
        return CircuitBreakerDecision(
            version=CIRCUIT_BREAKER_VERSION,
            mode=mode,
            action="allow",
            lockout_active=True,
            lockout_status=lockout_state.status,
            lockout_reason=lockout_state.reason,
            runtime_effect="observe_only_would_block_in_block_mode",
            reasons=reasons + ["observe_mode_allow"],
        )

    if mode == "warn":
        return CircuitBreakerDecision(
            version=CIRCUIT_BREAKER_VERSION,
            mode=mode,
            action="warn",
            lockout_active=True,
            lockout_status=lockout_state.status,
            lockout_reason=lockout_state.reason,
            runtime_effect="warn_only_order_still_allowed",
            reasons=reasons + ["warn_mode_allow"],
        )

    # mode == "block"
    return CircuitBreakerDecision(
        version=CIRCUIT_BREAKER_VERSION,
        mode=mode,
        action="block",
        lockout_active=True,
        lockout_status=lockout_state.status,
        lockout_reason=lockout_state.reason,
        runtime_effect="buy_blocked_by_regime_circuit_breaker",
        reasons=reasons + ["block_mode_active"],
    )
