"""Sizing stage interfaces and final sizing helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Callable

from services.signal_models import ApprovalResult, SizingDecision as PipelineSizingDecision


@dataclass(frozen=True)
class SizeCap:
    source: str
    cap_pct: float
    reason: str | None = None


@dataclass(frozen=True)
class SizingDecision:
    requested_size_pct: float
    final_size_pct: float
    dominant_limiter: str | None
    active_caps: list[SizeCap] = field(default_factory=list)
    conviction_stack: dict[str, Any] = field(default_factory=dict)


def collect_active_caps(account_state: dict[str, Any]) -> list[SizeCap]:
    caps: list[SizeCap] = []
    if (account_state.get("weak_prediction_setup_gate") or {}).get("triggered"):
        caps.append(SizeCap("weak_prediction_degraded", 0.50))
    if account_state.get("setup_degraded"):
        cap = (account_state["setup_degraded"] or {}).get("size_cap_pct")
        if cap is not None:
            caps.append(SizeCap("degraded_setup", float(cap)))
    if account_state.get("unrecognized_label_cap"):
        caps.append(
            SizeCap(
                "unrecognized_label",
                float((account_state["unrecognized_label_cap"] or {}).get("cap_pct", 99)),
            )
        )
    if account_state.get("prediction_confident_weak_cap"):
        caps.append(
            SizeCap(
                "prediction_confident_weak",
                float((account_state["prediction_confident_weak_cap"] or {}).get("cap_pct", 99)),
            )
        )
    if account_state.get("session_momentum_size_cap"):
        caps.append(
            SizeCap(
                "session_momentum",
                float((account_state["session_momentum_size_cap"] or {}).get("cap_pct", 99)),
            )
        )
    if account_state.get("strategy_score_size_cap"):
        caps.append(
            SizeCap(
                "strategy_brain",
                float((account_state["strategy_score_size_cap"] or {}).get("cap_pct", 99)),
            )
        )
    if account_state.get("setup_policy_override"):
        caps.append(SizeCap("setup_policy_override", 0.75))
    if account_state.get("max_position_size_pct_override") is not None:
        caps.append(
            SizeCap(
                "max_position_size_pct_override",
                float(account_state.get("max_position_size_pct_override")),
            )
        )
    return caps


def apply_size_cap(
    account_state: dict[str, Any],
    *,
    cap_pct: float,
    state_key: str,
    payload: dict[str, Any],
) -> float:
    existing = account_state.get("max_position_size_pct_override")
    cap_pct = float(cap_pct)
    account_state["max_position_size_pct_override"] = (
        min(float(existing), cap_pct) if existing is not None else cap_pct
    )
    account_state[state_key] = payload
    return account_state["max_position_size_pct_override"]


def build_conviction_stack(
    *,
    action: str,
    account_state: dict[str, Any],
    ml_prediction_bucket: Callable[[Any], str],
    compute_dominant_limiter: Callable[[dict[str, Any]], str],
) -> dict[str, Any]:
    if action != "buy":
        return {}
    ml_raw = (account_state.get("prediction_gate") or {}).get("ml_prediction_score")
    conviction_stack = {
        "buy_opportunity": (account_state.get("buy_opportunity") or {}).get(
            "buy_opportunity_recommendation"
        ),
        "strategy_score": float(
            (account_state.get("strategy_observation") or {})
            .get("trader_brain", {})
            .get("score")
            or 0
        ),
        "session_severity": (account_state.get("session_momentum_gate") or {}).get("severity"),
        "ml_bucket": ml_prediction_bucket(ml_raw),
        "effective_cap_pct": account_state.get("max_position_size_pct_override"),
    }
    account_state["conviction_stack"] = conviction_stack
    account_state["dominant_limiter"] = compute_dominant_limiter(account_state)
    return conviction_stack


def apply_final_sizing(
    *,
    symbol: str,
    action: str,
    decision: dict[str, Any],
    risk_multiplier: float,
    account_state: dict[str, Any],
    apply_buy_opportunity_sizing: Callable[..., float],
    log: Any = None,
) -> SizingDecision:
    requested = float(decision.get("position_size_pct") or 1.0)
    capped_request = requested
    max_size_override = account_state.get("max_position_size_pct_override")

    if action == "buy" and max_size_override is not None:
        capped_request = min(requested, float(max_size_override))
        if capped_request < requested:
            decision["position_size_pct"] = capped_request
            if log:
                log.warning(
                    f"Position size capped for {symbol}: "
                    f"{requested:.2f}% -> {capped_request:.2f}% due to setup_policy_override"
                )

    final_pct = apply_buy_opportunity_sizing(
        symbol=symbol,
        action=action,
        base_position_size_pct=capped_request,
        risk_multiplier=risk_multiplier,
        account_state=account_state,
    )

    return SizingDecision(
        requested_size_pct=requested,
        final_size_pct=final_pct,
        dominant_limiter=account_state.get("dominant_limiter"),
        active_caps=collect_active_caps(account_state),
        conviction_stack=account_state.get("conviction_stack") or {},
    )


class SizingService:
    def size(self, approval: ApprovalResult) -> PipelineSizingDecision:
        decision = approval.decision or {}
        return PipelineSizingDecision(
            position_size_pct=decision.get("position_size_pct"),
            stop_loss_pct=decision.get("stop_loss_pct"),
            take_profit_pct=decision.get("take_profit_pct"),
            reason=approval.reason,
        )
