"""Regime-driven risk, hedge, and re-entry protocol decisions.

This module emits protocol recommendations only. It deliberately does not call
Alpaca, cancel orders, liquidate positions, short hedges, or rebuild holdings.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from services.persistent_lockout_service import PersistentLockoutService


REGIME_RISK_PROTOCOL_VERSION = "regime_risk_protocol_v1"


@dataclass(frozen=True)
class RegimeRiskProtocolDecision:
    version: str
    action: str
    severity: str
    lockout_required: bool
    hedge_symbol: str
    hedge_ratio: float | None
    tranche_count: int | None
    runtime_effect: str
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def crash_risk_protocol(
    *,
    regime_history: list[int],
    lockout_active: bool = False,
    hedge_symbol: str = "SPY",
    hedge_ratio: float = 0.5,
    trigger_regime: int = 2,
    required_hits: int = 4,
    window: int = 5,
    mode: str = "hedge",
) -> RegimeRiskProtocolDecision:
    recent = list(regime_history or [])[-window:]
    hits = sum(1 for item in recent if item == trigger_regime)
    reasons = [f"regime_{trigger_regime}_hits={hits}_of_{window}"]
    if lockout_active:
        return RegimeRiskProtocolDecision(
            version=REGIME_RISK_PROTOCOL_VERSION,
            action="hold_lockout",
            severity="critical",
            lockout_required=True,
            hedge_symbol=hedge_symbol,
            hedge_ratio=None,
            tranche_count=None,
            runtime_effect="protocol_recommendation_only",
            reasons=reasons + ["persistent lockout already active"],
        )
    if hits >= required_hits:
        action = "safe_exit_required" if mode == "liquidate" else "delta_hedge_required"
        return RegimeRiskProtocolDecision(
            version=REGIME_RISK_PROTOCOL_VERSION,
            action=action,
            severity="critical",
            lockout_required=True,
            hedge_symbol=hedge_symbol,
            hedge_ratio=hedge_ratio if action == "delta_hedge_required" else None,
            tranche_count=None,
            runtime_effect="protocol_recommendation_only",
            reasons=reasons + ["cooldown window confirmed crash regime"],
        )
    return RegimeRiskProtocolDecision(
        version=REGIME_RISK_PROTOCOL_VERSION,
        action="stand_down",
        severity="normal",
        lockout_required=False,
        hedge_symbol=hedge_symbol,
        hedge_ratio=None,
        tranche_count=None,
        runtime_effect="protocol_recommendation_only",
        reasons=reasons + ["crash regime not stable enough"],
    )


def reentry_protocol(
    *,
    current_regime: int | None,
    stability_counter: int,
    current_status: str = "normal",
    target_regime: int = 0,
    required_stability: int = 5,
    tranches_total: int = 4,
    within_execution_window: bool = True,
) -> RegimeRiskProtocolDecision:
    reasons = [
        f"current_regime={current_regime}",
        f"stability_counter={stability_counter}",
        f"required_stability={required_stability}",
    ]
    if not within_execution_window:
        return RegimeRiskProtocolDecision(
            version=REGIME_RISK_PROTOCOL_VERSION,
            action="delay_reentry",
            severity="caution",
            lockout_required=current_status in {"lockout", "rebuilding"},
            hedge_symbol="SPY",
            hedge_ratio=None,
            tranche_count=tranches_total,
            runtime_effect="protocol_recommendation_only",
            reasons=reasons + ["outside preferred 10:30-15:30 ET re-entry window"],
        )
    if current_regime == target_regime and stability_counter >= required_stability:
        return RegimeRiskProtocolDecision(
            version=REGIME_RISK_PROTOCOL_VERSION,
            action="begin_tranched_reentry",
            severity="recovery",
            lockout_required=True,
            hedge_symbol="SPY",
            hedge_ratio=None,
            tranche_count=tranches_total,
            runtime_effect="protocol_recommendation_only",
            reasons=reasons + ["quiet bull regime stable; remove hedge then rebuild in tranches"],
        )
    return RegimeRiskProtocolDecision(
        version=REGIME_RISK_PROTOCOL_VERSION,
        action="stand_down",
        severity="normal",
        lockout_required=current_status in {"lockout", "rebuilding"},
        hedge_symbol="SPY",
        hedge_ratio=None,
        tranche_count=None,
        runtime_effect="protocol_recommendation_only",
        reasons=reasons + ["target regime not stable enough"],
    )


def apply_protocol_lockout_state(
    *,
    decision: RegimeRiskProtocolDecision,
    lockout_path: Path | str,
) -> dict[str, Any]:
    """Apply only persistent state effects from a protocol recommendation.

    This intentionally does not place or cancel broker orders. It lets the live
    system honor a global lockout/rebuilding state while execution authority is
    reviewed separately.
    """
    service = PersistentLockoutService(lockout_path)
    if decision.action in {"delta_hedge_required", "safe_exit_required", "hold_lockout"}:
        state = service.activate(
            reason=decision.action,
            payload={
                "protocol": decision.to_dict(),
            },
        )
    elif decision.action == "begin_tranched_reentry":
        state = service.set_rebuilding(
            reason=decision.action,
            payload={
                "protocol": decision.to_dict(),
            },
        )
    else:
        state = service.read()
    return {
        "runtime_effect": "persistent_state_only_no_broker_orders",
        "decision_action": decision.action,
        "lockout_state": state.to_dict(),
    }
