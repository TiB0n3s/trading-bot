#!/usr/bin/env python3
"""
Adaptive BUY confirmation report — observe-only.

Compares current fixed 3-BUY confirmation rule against the future adaptive
2/3/4-confirmation requirement.

Usage:
  python3 adaptive_confirmation_report.py
"""

from config import APPROVED_SYMBOLS, ADAPTIVE_BUY_CONFIRMATION_ENABLED
from app import (
    _load_market_context,
    _market_bias,
    _signal_history,
    _trend_table,
    _refresh_signal_history,
    _compute_trend,
    _required_buy_confirmations,
    _symbol_market_alignment,
)
from macro_risk import get_macro_risk
from pathlib import Path


def short(v, width):
    if v is None:
        return "-"
    s = str(v)
    return s if len(s) <= width else s[: width - 1] + "…"


def main():
    _load_market_context()
    macro_risk = get_macro_risk(Path(__file__).resolve().parent)

    rows = []

    for sym in sorted(APPROVED_SYMBOLS):
        _refresh_signal_history(sym)
        trend = _compute_trend(_signal_history.get(sym, []))
        _trend_table[sym] = trend

        alignment = _symbol_market_alignment(sym)
        adaptive = _required_buy_confirmations(sym, {
            "macro_risk": macro_risk,
            "market_alignment": alignment,
        })

        bias = _market_bias.get(sym) or {}

        rows.append({
            "symbol": sym,
            "trend": trend,
            "adaptive": adaptive,
            "bias": bias,
            "alignment": alignment,
        })

    print("=" * 150)
    print("  Adaptive BUY Confirmation Report — observe-only")
    print("=" * 150)
    print(f"  macro_regime : {macro_risk.get('macro_regime')}")
    print(f"  risk_mult    : {macro_risk.get('risk_multiplier')}")
    print()
    if ADAPTIVE_BUY_CONFIRMATION_ENABLED:
        print("  Live rule: adaptive BUY confirmation is ENABLED.")
        print("  BUY signals below the Adapt requirement will be rejected.")
    else:
        print("  Live rule: adaptive BUY confirmation is OBSERVE-ONLY.")
        print("  BUY signals below the Adapt requirement will only be logged.")
    print()

    headers = [
        "Sym", "Trend", "Cnt", "Fixed", "Adapt", "Bias", "Risk", "Entry",
        "Aligned", "Benchmark", "Reason"
    ]
    widths = [6, 18, 5, 7, 7, 9, 10, 18, 9, 10, 45]
    fmt = " ".join(f"{{:<{w}}}" for w in widths)

    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))

    lowered = same = raised = 0

    for r in rows:
        sym = r["symbol"]
        trend = r["trend"]
        adaptive = r["adaptive"]
        bias = r["bias"]
        alignment = r["alignment"]

        fixed = adaptive.get("current_rule_required_buy_confirmations", 3)
        adapt = adaptive.get("required_buy_confirmations", 3)

        if adapt < fixed:
            lowered += 1
        elif adapt > fixed:
            raised += 1
        else:
            same += 1

        trend_txt = f"{trend.get('direction')}/{trend.get('strength')}"
        aligned = alignment.get("aligned_for_buy")
        aligned_txt = "yes" if aligned is True else "no" if aligned is False else "-"

        print(fmt.format(
            sym,
            short(trend_txt, 18),
            str(trend.get("consecutive_count")),
            str(fixed),
            str(adapt),
            short(bias.get("bias"), 9),
            short(bias.get("risk_level"), 10),
            short(bias.get("entry_quality"), 18),
            aligned_txt,
            short(alignment.get("benchmark"), 10),
            short(adaptive.get("reason"), 45),
        ))

    print()
    print(f"Adaptive would lower requirement : {lowered}")
    print(f"Adaptive would keep requirement  : {same}")
    print(f"Adaptive would raise requirement : {raised}")
    print()
    if ADAPTIVE_BUY_CONFIRMATION_ENABLED:
        print("Live mode: adaptive BUY confirmation is active.")
    else:
        print("Observe-only: adaptive BUY confirmation is not active until the env flag is enabled.")


if __name__ == "__main__":
    main()
