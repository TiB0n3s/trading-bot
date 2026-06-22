"""Sizing and conviction policy.

This module owns size caps, conviction-stack limiter attribution, and adaptive
buy-opportunity sizing. It does not approve trades or submit orders.
"""

from __future__ import annotations

import logging
import os
from typing import Any

from services.observability import record_dominant_limiter
from services.policy_controls import policy_family_enabled

logger = logging.getLogger(__name__)


def env_float(name: str, default: float) -> float:
    try:
        return float(os.getenv(name, str(default)))
    except Exception:
        return default


def buy_opportunity_sizing_enabled() -> bool:
    if not policy_family_enabled("sizing"):
        return False
    return os.getenv("BUY_OPPORTUNITY_SIZING_ENABLED", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def setup_quality_sizing_enabled() -> bool:
    if not policy_family_enabled("sizing"):
        return False
    return os.getenv("SETUP_QUALITY_SIZING_ENABLED", "true").strip().lower() in (
        "1",
        "true",
        "yes",
        "on",
    )


def compute_dominant_limiter(account_state: dict[str, Any]) -> str:
    """Return the label of the tightest active pre-execution size cap."""
    if not policy_family_enabled("sizing"):
        record_dominant_limiter("sizing_policy_disabled")
        return "sizing_policy_disabled"

    caps = []
    if (account_state.get("weak_prediction_setup_gate") or {}).get("triggered"):
        caps.append(("weak_prediction_degraded", 0.50))
    if account_state.get("setup_degraded"):
        caps.append(("degraded_setup", account_state["setup_degraded"].get("size_cap_pct", 99)))
    if account_state.get("unrecognized_label_cap"):
        caps.append(
            ("unrecognized_label", account_state["unrecognized_label_cap"].get("cap_pct", 99))
        )
    if account_state.get("prediction_confident_weak_cap"):
        caps.append(
            (
                "prediction_confident_weak",
                account_state["prediction_confident_weak_cap"].get("cap_pct", 99),
            )
        )
    if account_state.get("session_momentum_size_cap"):
        caps.append(
            ("session_momentum", account_state["session_momentum_size_cap"].get("cap_pct", 99))
        )
    if account_state.get("late_chase_size_cap"):
        caps.append(("late_chase", account_state["late_chase_size_cap"].get("cap_pct", 99)))
    if account_state.get("unclassified_extended_size_cap"):
        caps.append(
            (
                "unclassified_extended",
                account_state["unclassified_extended_size_cap"].get("cap_pct", 99),
            )
        )
    if account_state.get("advisory_feature_size_cap"):
        caps.append(
            ("advisory_features", account_state["advisory_feature_size_cap"].get("cap_pct", 99))
        )
    if account_state.get("strategy_score_size_cap"):
        caps.append(("strategy_brain", account_state["strategy_score_size_cap"].get("cap_pct", 99)))
    if account_state.get("setup_policy_override"):
        caps.append(("setup_policy_override", 0.75))
    if account_state.get("setup_quality_size_cap"):
        caps.append(("setup_quality", account_state["setup_quality_size_cap"].get("cap_pct", 99)))
    if account_state.get("slippage_kelly_size_cap"):
        caps.append(("slippage_kelly", account_state["slippage_kelly_size_cap"].get("cap_pct", 99)))
    limiter = "uncapped" if not caps else min(caps, key=lambda x: x[1])[0]
    record_dominant_limiter(limiter)
    return limiter


def apply_buy_opportunity_sizing(
    *,
    symbol: str,
    action: str,
    base_position_size_pct: float,
    risk_multiplier: float,
    account_state: dict[str, Any],
    log: logging.Logger | None = None,
) -> float:
    """Apply adaptive BUY sizing without approving or rejecting the trade."""
    log = log or logger
    base_position_size_pct = float(base_position_size_pct or 0)
    # Defense-in-depth: the macro risk multiplier may only tighten, never
    # amplify, sizing. Clamp to [0, 1] here too in case an unclamped value
    # reaches sizing from any path. (#7)
    risk_multiplier = max(0.0, min(1.0, float(risk_multiplier or 1.0)))
    adjusted = base_position_size_pct * risk_multiplier

    if action != "buy":
        return adjusted

    buy_opp = (account_state or {}).get("buy_opportunity") or {}
    setup_quality = (account_state or {}).get("setup_quality") or {}

    if not buy_opportunity_sizing_enabled():
        account_state["buy_opportunity_sizing"] = {
            "enabled": False,
            "original_pct": adjusted,
            "final_pct": adjusted,
            "reason": "BUY opportunity sizing disabled",
        }
        return adjusted

    score_raw = buy_opp.get("buy_opportunity_score")
    rec = buy_opp.get("buy_opportunity_recommendation")

    try:
        score = float(score_raw)
    except Exception:
        score = None

    setup_score_raw = setup_quality.get("score")
    try:
        setup_score = float(setup_score_raw)
    except Exception:
        setup_score = None
    setup_recommendation = setup_quality.get("recommendation")

    if setup_quality_sizing_enabled() and setup_quality:
        setup_cap = None
        if setup_recommendation == "avoid" or (setup_score is not None and setup_score < 40):
            setup_cap = env_float("SETUP_QUALITY_AVOID_CAP_PCT", 0.35)
        elif setup_recommendation == "watch" or (setup_score is not None and setup_score < 55):
            setup_cap = env_float("SETUP_QUALITY_WATCH_CAP_PCT", 0.50)

        if setup_cap is not None:
            account_state["setup_quality_size_cap"] = {
                "enabled": True,
                "recommendation": setup_recommendation,
                "score": setup_score,
                "cap_pct": setup_cap,
                "source": setup_quality.get("source"),
                "reason": (
                    f"setup_quality sizing cap: rec={setup_recommendation} "
                    f"score={setup_score} cap={setup_cap}"
                ),
            }
            adjusted = min(adjusted, setup_cap)
            existing_override = account_state.get("max_position_size_pct_override")
            if existing_override is None or setup_cap < float(existing_override):
                account_state["dominant_limiter"] = "setup_quality"

    small_cap = env_float("BUY_OPPORTUNITY_SMALL_CAP_PCT", 1.25)
    watch_cap = env_float("BUY_OPPORTUNITY_WATCH_CAP_PCT", 0.75)
    avoid_cap = env_float("BUY_OPPORTUNITY_AVOID_CAP_PCT", 0.50)

    cap = None
    bucket = "unscored"

    if rec == "strong_buy_candidate" or (score is not None and score >= 10):
        bucket = "strong_buy_candidate"
        cap = None

        trader_brain = (account_state.get("strategy_observation") or {}).get("trader_brain", {})
        strategy_score = float(trader_brain.get("score") or 0)
        session_severity = (account_state.get("session_momentum_gate") or {}).get("severity")
        setup_action = setup_quality.get("policy_action") or (
            account_state.get("setup_observation") or {}
        ).get("setup_policy_action")
        setup_recommendation = str(setup_recommendation or "").lower()
        setup_score = setup_score if setup_score is not None else 0.0
        has_strong_context = (
            strategy_score >= 70
            and session_severity in ("pass", None)
            and setup_action in ("boost", "allow")
            and setup_recommendation in ("buy", "favorable", "strong_buy_candidate")
            and setup_score >= 70
            and account_state.get("max_position_size_pct_override") is None
            and not account_state.get("setup_quality_size_cap")
        )
        if has_strong_context:
            lift_mult = env_float("BUY_OPPORTUNITY_STRONG_CONVICTION_LIFT_MULT", 1.10)
            max_lift = env_float("BUY_OPPORTUNITY_STRONG_CONVICTION_MAX_PCT", 1.50)
            final_pct = min(adjusted * lift_mult, max_lift)
            account_state["buy_opportunity_sizing"] = {
                "enabled": True,
                "bucket": "strong_buy_candidate_lift",
                "score": score,
                "recommendation": rec,
                "original_pct": round(adjusted, 4),
                "lift_mult": lift_mult,
                "final_pct": round(final_pct, 4),
                "reason": (
                    f"strong_conviction_lift: score={score} tb={strategy_score:.0f} "
                    f"session={session_severity} setup={setup_action} "
                    f"lift={lift_mult}x final={final_pct:.3f}"
                ),
            }
            log.info(
                f"BUY strong-conviction lift for {symbol}: "
                f"score={score} tb={strategy_score:.0f} {adjusted:.3f}% -> {final_pct:.3f}%"
            )
            return final_pct

    elif rec == "small_buy_candidate" or (score is not None and score >= 7):
        bucket = "small_buy_candidate"
        cap = small_cap
    elif rec == "watch" or (score is not None and score >= 4):
        bucket = "watch"
        cap = watch_cap
    elif rec == "avoid" or score is not None:
        bucket = "avoid"
        cap = avoid_cap
    else:
        account_state["buy_opportunity_sizing"] = {
            "enabled": True,
            "bucket": bucket,
            "score": score,
            "recommendation": rec,
            "original_pct": adjusted,
            "final_pct": adjusted,
            "reason": "BUY opportunity score missing; size unchanged",
        }
        return adjusted

    final_pct = min(adjusted, cap) if cap is not None else adjusted

    account_state["buy_opportunity_sizing"] = {
        "enabled": True,
        "bucket": bucket,
        "score": score,
        "recommendation": rec,
        "original_pct": round(adjusted, 4),
        "cap_pct": cap,
        "final_pct": round(final_pct, 4),
        "reason": (
            f"BUY opportunity sizing bucket={bucket}, score={score}, "
            f"rec={rec}, original={adjusted:.3f}, cap={cap}, final={final_pct:.3f}"
        ),
    }

    log.warning(
        f"BUY opportunity sizing for {symbol}: "
        f"bucket={bucket} score={score} rec={rec} "
        f"original_pct={adjusted:.3f} cap={cap} final_pct={final_pct:.3f}"
    )
    return final_pct
