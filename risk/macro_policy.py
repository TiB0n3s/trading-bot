#!/usr/bin/env python3
"""
Macro policy helpers.

Read-only mapping from market regime to account-level risk policy.

This mirrors the current macro_risk.py behavior so it can be adopted gradually
without changing live trading behavior.
"""

from __future__ import annotations

from typing import Any


DEFAULT_MACRO_POLICY = {
    "macro_regime": "normal",
    "risk_multiplier": 1.0,
    "max_new_positions": 8,
    "block_new_buys": False,
    "reason": "Default normal regime",
}


def normalize_regime(value: Any) -> str:
    """Normalize regime/sentiment strings to snake_case."""
    if value is None:
        return "normal"

    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def policy_for_regime(regime: Any) -> dict[str, Any]:
    """Return the risk policy for a normalized or raw macro regime."""
    normalized = normalize_regime(regime)

    if normalized in ("risk_on", "bullish", "normal"):
        return {
            "macro_regime": normalized,
            "risk_multiplier": 1.0,
            "max_new_positions": 8,
            "block_new_buys": False,
            "reason": "Macro context normal/risk-on",
        }

    if normalized in ("caution", "mixed", "neutral"):
        return {
            "macro_regime": normalized,
            "risk_multiplier": 0.75,
            "max_new_positions": 6,
            "block_new_buys": False,
            "reason": "Macro context caution/mixed",
        }

    if normalized in ("defensive", "risk_off"):
        return {
            "macro_regime": normalized,
            "risk_multiplier": 0.50,
            "max_new_positions": 4,
            "block_new_buys": False,
            "reason": "Macro context defensive/risk-off",
        }

    if normalized in ("capital_preservation", "panic", "crisis"):
        return {
            "macro_regime": normalized,
            "risk_multiplier": 0.0,
            "max_new_positions": 0,
            "block_new_buys": True,
            "reason": "Capital preservation regime blocks new buys",
        }

    return {
        "macro_regime": normalized,
        "risk_multiplier": 0.75,
        "max_new_positions": 6,
        "block_new_buys": False,
        "reason": f"Unknown macro regime '{normalized}'; using caution defaults",
    }


def apply_macro_overrides(
    policy: dict[str, Any],
    context: dict[str, Any] | None,
) -> dict[str, Any]:
    """Apply explicit top-level market_context overrides to a policy dict."""
    context = context or {}
    out = dict(policy)
    applied = []

    if isinstance(context.get("max_new_positions"), int):
        out["max_new_positions"] = context["max_new_positions"]
        applied.append(f"max_new_positions={context['max_new_positions']}")

    risk_multiplier = context.get("risk_multiplier")
    if isinstance(risk_multiplier, (int, float)) and not isinstance(risk_multiplier, bool):
        out["risk_multiplier"] = float(risk_multiplier)
        applied.append(f"risk_multiplier={risk_multiplier}")

    if isinstance(context.get("block_new_buys"), bool):
        out["block_new_buys"] = context["block_new_buys"]
        applied.append(f"block_new_buys={context['block_new_buys']}")

    if applied:
        out["reason"] = f"{out.get('reason', '')} (brief overrides: {', '.join(applied)})"

    return out


def policy_from_market_context(context: dict[str, Any] | None) -> dict[str, Any]:
    """Return macro policy from a market_context-style dict."""
    context = context or {}

    regime = (
        context.get("macro_regime")
        or context.get("macro_sentiment")
        or "normal"
    )

    return apply_macro_overrides(
        policy_for_regime(regime),
        context,
    )
