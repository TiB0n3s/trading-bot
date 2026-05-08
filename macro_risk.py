import json
from pathlib import Path

DEFAULT_MACRO_RISK = {
    "macro_regime": "normal",
    "risk_multiplier": 1.0,
    "max_new_positions": 8,
    "block_new_buys": False,
    "reason": "Default normal regime",
}

# Fields the brief can set explicitly to override the regime-derived defaults.
# These are read from the top level of market_context.json after the regime
# mapping is applied, so the brief author can tighten (or loosen) any single
# dimension without having to invent a new regime label.
EXPLICIT_OVERRIDE_FIELDS = ("max_new_positions", "risk_multiplier", "block_new_buys")


def get_macro_risk(base_dir: Path | None = None):
    base_dir = base_dir or Path(__file__).parent
    path = base_dir / "market_context.json"

    if not path.exists():
        return {
            **DEFAULT_MACRO_RISK,
            "macro_regime": "unknown",
            "risk_multiplier": 0.75,
            "max_new_positions": 6,
            "reason": "market_context.json missing; using caution defaults",
        }

    try:
        ctx = json.loads(path.read_text())
        regime = (
            ctx.get("macro_regime")
            or ctx.get("macro_sentiment")
            or "normal"
        )

        regime = str(regime).lower().replace(" ", "_").replace("-", "_")

        if regime in ("risk_on", "bullish", "normal"):
            policy = {
                "macro_regime": regime,
                "risk_multiplier": 1.0,
                "max_new_positions": 8,
                "block_new_buys": False,
                "reason": "Macro context normal/risk-on",
            }
        elif regime in ("caution", "mixed", "neutral"):
            policy = {
                "macro_regime": regime,
                "risk_multiplier": 0.75,
                "max_new_positions": 6,
                "block_new_buys": False,
                "reason": "Macro context caution/mixed",
            }
        elif regime in ("defensive", "risk_off"):
            policy = {
                "macro_regime": regime,
                "risk_multiplier": 0.50,
                "max_new_positions": 4,
                "block_new_buys": False,
                "reason": "Macro context defensive/risk-off",
            }
        elif regime in ("capital_preservation", "panic", "crisis"):
            policy = {
                "macro_regime": regime,
                "risk_multiplier": 0.0,
                "max_new_positions": 0,
                "block_new_buys": True,
                "reason": "Capital preservation regime blocks new buys",
            }
        else:
            policy = {
                "macro_regime": regime,
                "risk_multiplier": 0.75,
                "max_new_positions": 6,
                "block_new_buys": False,
                "reason": f"Unknown macro regime '{regime}'; using caution defaults",
            }

        # Apply explicit overrides from the brief, if present at top level.
        # The brief can tighten or loosen specific dimensions independent of regime.
        applied = []
        if isinstance(ctx.get("max_new_positions"), int):
            policy["max_new_positions"] = ctx["max_new_positions"]
            applied.append(f"max_new_positions={ctx['max_new_positions']}")
        rm = ctx.get("risk_multiplier")
        if isinstance(rm, (int, float)) and not isinstance(rm, bool):
            policy["risk_multiplier"] = float(rm)
            applied.append(f"risk_multiplier={rm}")
        if isinstance(ctx.get("block_new_buys"), bool):
            policy["block_new_buys"] = ctx["block_new_buys"]
            applied.append(f"block_new_buys={ctx['block_new_buys']}")
        if applied:
            policy["reason"] = f"{policy['reason']} (brief overrides: {', '.join(applied)})"

        return policy

    except Exception as e:
        return {
            **DEFAULT_MACRO_RISK,
            "macro_regime": "error",
            "risk_multiplier": 0.75,
            "max_new_positions": 6,
            "reason": f"Failed to parse market_context.json: {e}",
        }
