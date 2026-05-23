import json
from pathlib import Path

from risk.macro_policy import DEFAULT_MACRO_POLICY, policy_from_market_context


def get_macro_risk(base_dir: Path | None = None):
    base_dir = base_dir or Path(__file__).parent
    path = base_dir / "market_context.json"

    if not path.exists():
        return {
            **DEFAULT_MACRO_POLICY,
            "macro_regime": "unknown",
            "risk_multiplier": 0.75,
            "max_new_positions": 6,
            "reason": "market_context.json missing; using caution defaults",
        }

    try:
        ctx = json.loads(path.read_text())
        return policy_from_market_context(ctx)

    except Exception as e:
        return {
            **DEFAULT_MACRO_POLICY,
            "macro_regime": "error",
            "risk_multiplier": 0.75,
            "max_new_positions": 6,
            "reason": f"Failed to parse market_context.json: {e}",
        }
