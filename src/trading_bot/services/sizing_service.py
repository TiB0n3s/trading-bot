"""Sizing stage interfaces and final sizing helpers."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any, Callable

if TYPE_CHECKING:
    from trading_bot.signals.live.gate_context import DecisionTrace as OutputTrace

from config.risk import load_risk_config
from services.signal_models import ApprovalResult
from services.signal_models import SizingDecision as PipelineSizingDecision
from services.slippage_kelly_sizing_service import calculate_slippage_adjusted_kelly_cap

_risk_cfg = load_risk_config()


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
    if account_state.get("late_chase_size_cap"):
        caps.append(
            SizeCap(
                "late_chase",
                float((account_state["late_chase_size_cap"] or {}).get("cap_pct", 99)),
                (account_state["late_chase_size_cap"] or {}).get("reason"),
            )
        )
    if account_state.get("unclassified_extended_size_cap"):
        caps.append(
            SizeCap(
                "unclassified_extended",
                float((account_state["unclassified_extended_size_cap"] or {}).get("cap_pct", 99)),
                (account_state["unclassified_extended_size_cap"] or {}).get("reason"),
            )
        )
    if account_state.get("advisory_feature_size_cap"):
        caps.append(
            SizeCap(
                "advisory_features",
                float((account_state["advisory_feature_size_cap"] or {}).get("cap_pct", 99)),
                (account_state["advisory_feature_size_cap"] or {}).get("reason"),
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
    if account_state.get("setup_quality_size_cap"):
        caps.append(
            SizeCap(
                "setup_quality",
                float((account_state["setup_quality_size_cap"] or {}).get("cap_pct", 99)),
                (account_state["setup_quality_size_cap"] or {}).get("reason"),
            )
        )
    if account_state.get("slippage_kelly_size_cap"):
        caps.append(
            SizeCap(
                "slippage_kelly",
                float((account_state["slippage_kelly_size_cap"] or {}).get("cap_pct", 99)),
                (account_state["slippage_kelly_size_cap"] or {}).get("reason"),
            )
        )
    buy_opportunity_sizing = account_state.get("buy_opportunity_sizing") or {}
    if buy_opportunity_sizing.get("cap_pct") is not None:
        caps.append(
            SizeCap(
                "buy_opportunity",
                float(buy_opportunity_sizing.get("cap_pct")),
                buy_opportunity_sizing.get("reason"),
            )
        )
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
    gate_trace: OutputTrace | None = None,
) -> float:
    existing = account_state.get("max_position_size_pct_override")
    cap_pct = float(cap_pct)
    account_state["max_position_size_pct_override"] = (
        min(float(existing), cap_pct) if existing is not None else cap_pct
    )
    account_state[state_key] = payload
    if gate_trace is not None:
        gate_trace.record(state_key, payload)
        gate_trace.record("max_position_size_pct_override", account_state["max_position_size_pct_override"])
    return account_state["max_position_size_pct_override"]


def build_conviction_stack(
    *,
    action: str,
    account_state: dict[str, Any],
    ml_prediction_bucket: Callable[[Any], str],
    compute_dominant_limiter: Callable[[dict[str, Any]], str],
    gate_trace: OutputTrace | None = None,
) -> dict[str, Any]:
    if action != "buy":
        return {}
    ml_raw = (account_state.get("prediction_gate") or {}).get("ml_prediction_score")
    conviction_stack = {
        "buy_opportunity": (account_state.get("buy_opportunity") or {}).get(
            "buy_opportunity_recommendation"
        ),
        "strategy_score": float(
            (account_state.get("strategy_observation") or {}).get("trader_brain", {}).get("score")
            or 0
        ),
        "session_severity": (account_state.get("session_momentum_gate") or {}).get("severity"),
        "ml_bucket": ml_prediction_bucket(ml_raw),
        "effective_cap_pct": account_state.get("max_position_size_pct_override"),
    }
    account_state["conviction_stack"] = conviction_stack
    account_state["dominant_limiter"] = compute_dominant_limiter(account_state)
    if gate_trace is not None:
        gate_trace.record("conviction_stack", conviction_stack)
        gate_trace.record("dominant_limiter", account_state["dominant_limiter"])
    return conviction_stack


def _apply_final_sizing_invariants(
    *,
    symbol: str,
    action: str,
    final_pct: float,
    account_state: dict[str, Any],
    log: Any = None,
) -> list[SizeCap]:
    """Hard sizing invariants applied independently of per-condition caps.

    Returns SizeCap entries the caller folds into the final size:
      * ``absolute_ceiling`` (#6): MAX_POSITION_SIZE_PCT backstop against a
        malformed/hallucinated Claude size or an uncapped sizing bucket.
      * ``projected_exposure`` (#5, buys only): caps so that
        (existing position value + this order's notional) does not exceed the
        per-symbol exposure cap — applied even on a first entry.
    """
    caps: list[SizeCap] = []

    ceiling = float(_risk_cfg.max_position_size_pct)
    if final_pct > ceiling:
        caps.append(SizeCap("absolute_ceiling", ceiling, f"hard ceiling {ceiling:.2f}%"))
        if log:
            log.warning(
                f"Position size ceiling for {symbol}: "
                f"{final_pct:.2f}% -> {ceiling:.2f}% (MAX_POSITION_SIZE_PCT)"
            )

    if action == "buy":
        balance = float(account_state.get("balance") or 0)
        existing = account_state.get("current_symbol_position") or {}
        try:
            existing_value = float(existing.get("qty") or 0) * float(
                existing.get("current_price") or 0
            )
        except Exception:
            existing_value = 0.0
        if balance > 0:
            cap_pct = float(_risk_cfg.per_symbol_exposure_cap_pct)
            existing_pct = existing_value / balance * 100.0
            headroom = max(0.0, cap_pct - existing_pct)
            if final_pct > headroom:
                caps.append(
                    SizeCap(
                        "projected_exposure",
                        round(headroom, 4),
                        (
                            f"per-symbol exposure cap {cap_pct:.2f}%: existing "
                            f"{existing_pct:.2f}% leaves {headroom:.2f}% headroom"
                        ),
                    )
                )
                account_state["projected_exposure_cap"] = {
                    "cap_pct": cap_pct,
                    "existing_pct": round(existing_pct, 4),
                    "headroom_pct": round(headroom, 4),
                }
                if log:
                    log.warning(
                        f"Projected per-symbol exposure cap for {symbol}: "
                        f"{final_pct:.2f}% -> {headroom:.2f}% "
                        f"(existing {existing_pct:.2f}% + order, cap {cap_pct:.2f}%)"
                    )
    return caps


def apply_final_sizing(
    *,
    symbol: str,
    action: str,
    decision: dict[str, Any],
    risk_multiplier: float,
    account_state: dict[str, Any],
    apply_buy_opportunity_sizing: Callable[..., float],
    log: Any = None,
    gate_trace: OutputTrace | None = None,
) -> SizingDecision:
    requested = float(decision.get("position_size_pct") or 1.0)
    capped_request = requested

    if action == "buy":
        slippage_kelly = calculate_slippage_adjusted_kelly_cap(
            account_state=account_state,
            action=action,
            requested_size_pct=requested,
        )
        account_state["slippage_kelly_sizing"] = slippage_kelly.to_dict()
        if gate_trace is not None:
            gate_trace.record("slippage_kelly_sizing", account_state["slippage_kelly_sizing"])
        if slippage_kelly.action in {"cap", "zero"} and slippage_kelly.cap_pct is not None:
            apply_size_cap(
                account_state,
                cap_pct=slippage_kelly.cap_pct,
                state_key="slippage_kelly_size_cap",
                payload={
                    "enabled": slippage_kelly.enabled,
                    "cap_pct": slippage_kelly.cap_pct,
                    "reason": slippage_kelly.reason,
                    "friction_ratio": slippage_kelly.friction_ratio,
                    "liquidity_stress_score": slippage_kelly.liquidity_stress_score,
                    "liquidity_stress_bucket": slippage_kelly.liquidity_stress_bucket,
                    "liquidity_stress_size_multiplier": (
                        slippage_kelly.liquidity_stress_size_multiplier
                    ),
                    "model_prob": slippage_kelly.model_prob,
                    "predicted_slippage_pct": slippage_kelly.predicted_slippage_pct,
                    "adjusted_risk_reward_ratio": (slippage_kelly.adjusted_risk_reward_ratio),
                    "runtime_effect": slippage_kelly.runtime_effect,
                    "version": slippage_kelly.version,
                },
            )

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

    invariant_caps = _apply_final_sizing_invariants(
        symbol=symbol,
        action=action,
        final_pct=final_pct,
        account_state=account_state,
        log=log,
    )
    if invariant_caps:
        final_pct = min(final_pct, *[cap.cap_pct for cap in invariant_caps])

    active_caps = collect_active_caps(account_state)
    active_caps.extend(invariant_caps)
    tightest_cap = min(active_caps, key=lambda cap: cap.cap_pct) if active_caps else None
    dominant_limiter = (
        tightest_cap.source
        if tightest_cap is not None
        else account_state.get("dominant_limiter") or "uncapped"
    )
    if action == "buy":
        account_state["dominant_limiter"] = dominant_limiter
        conviction_stack = dict(account_state.get("conviction_stack") or {})
        if conviction_stack:
            conviction_stack["effective_cap_pct"] = (
                tightest_cap.cap_pct
                if tightest_cap is not None
                else account_state.get("max_position_size_pct_override")
            )
            account_state["conviction_stack"] = conviction_stack
        if gate_trace is not None:
            gate_trace.record("dominant_limiter", dominant_limiter)
            gate_trace.record("conviction_stack", account_state.get("conviction_stack") or {})
    else:
        conviction_stack = account_state.get("conviction_stack") or {}

    return SizingDecision(
        requested_size_pct=requested,
        final_size_pct=final_pct,
        dominant_limiter=dominant_limiter,
        active_caps=active_caps,
        conviction_stack=conviction_stack,
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
