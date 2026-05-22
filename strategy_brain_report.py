#!/usr/bin/env python3
"""
Strategy Brain Report

Read-only dashboard for the bot's learning/intelligence layer.

Reads generated memory files:
- strategy_memory.json
- manual_strategy_overrides.json
- missed_opportunity_memory.json
- excursion_memory.json
- policy_backtest_summary.json

Purpose:
- Summarize what the bot has learned
- Highlight active manual overrides
- Surface gates that may be too strict or useful
- Surface entry/exit problems from MFE/MAE
- Surface policy backtest strictness/looseness
- Provide next-day review items

This does not place, cancel, or modify orders.
"""

import argparse
import json
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent

FILES = {
    "strategy_memory": BASE_DIR / "strategy_memory.json",
    "manual_overrides": BASE_DIR / "manual_strategy_overrides.json",
    "missed_opportunity": BASE_DIR / "missed_opportunity_memory.json",
    "excursion": BASE_DIR / "excursion_memory.json",
    "policy_backtest": BASE_DIR / "policy_backtest_summary.json",
}


def load_json(path):
    if not path.exists():
        return None, f"{path.name} not found"
    try:
        return json.loads(path.read_text()), None
    except Exception as e:
        return None, f"failed to parse {path.name}: {e}"


def print_header(title):
    print()
    print("── " + title + " " + "─" * max(0, 68 - len(title)))


def money(v):
    try:
        return f"${float(v):+.2f}"
    except Exception:
        return "$+0.00"


def pct(v):
    try:
        return f"{float(v):+.2f}%"
    except Exception:
        return "+0.00%"


def top_items(mapping, predicate=None, sort_key=None, limit=10):
    if not isinstance(mapping, dict):
        return []

    items = list(mapping.items())

    if predicate:
        items = [(k, v) for k, v in items if predicate(k, v)]

    if sort_key:
        items = sorted(items, key=lambda kv: sort_key(kv[0], kv[1]))
    else:
        items = sorted(items)

    return items[:limit]


def section_file_status(data):
    print_header("Source files")

    for key, path in FILES.items():
        obj, err = data[key]
        if err:
            print(f"  {key:<22} missing/error  {err}")
        else:
            generated = obj.get("generated_at") if isinstance(obj, dict) else None
            print(f"  {key:<22} loaded         generated_at={generated or '-'}")


def section_strategy_memory(strategy_memory):
    print_header("Strategy memory")

    if not strategy_memory:
        print("  No strategy_memory.json available.")
        return

    print(f"  generated_at          : {strategy_memory.get('generated_at')}")
    print(f"  trade_count           : {strategy_memory.get('trade_count')}")
    print(f"  lookback_days         : {strategy_memory.get('lookback_days')}")
    print(f"  manual_overrides      : {strategy_memory.get('manual_overrides_applied')}")
    print(f"  history_snapshot      : {strategy_memory.get('history_snapshot') or '-'}")

    symbols = strategy_memory.get("symbols") or {}

    print()
    print("  Active symbol recommendations:")
    print(f"  {'Symbol':<8} {'Rec':<9} {'Trades':>6} {'Expect':>9} {'Win%':>7} {'MinScore':>8} Reason")
    print(f"  {'-'*8} {'-'*9} {'-'*6} {'-'*9} {'-'*7} {'-'*8} {'-'*40}")

    interesting = top_items(
        symbols,
        predicate=lambda k, v: v.get("recommendation") in ("avoid", "caution", "favor") or v.get("manual_override"),
        sort_key=lambda k, v: (
            {"avoid": 0, "caution": 1, "favor": 2, "neutral": 3, "observe": 4}.get(v.get("recommendation"), 9),
            k,
        ),
        limit=25,
    )

    if not interesting:
        print("  No active caution/avoid/favor symbol recommendations.")
        return

    for sym, info in interesting:
        print(
            f"  {sym:<8} "
            f"{str(info.get('recommendation')):<9} "
            f"{int(info.get('trades') or 0):>6} "
            f"{float(info.get('expectancy') or 0):>9.2f} "
            f"{float(info.get('win_rate_pct') or 0):>7.1f} "
            f"{str(info.get('min_setup_score')):>8} "
            f"{(info.get('reason') or '')[:80]}"
        )


def section_manual_overrides(manual):
    print_header("Manual overrides")

    if not manual:
        print("  No manual_strategy_overrides.json available.")
        return

    symbols = manual.get("symbols") or {}

    if not symbols:
        print("  No manual symbol overrides active.")
        return

    print(f"  {'Symbol':<8} {'Rec':<9} {'MinScore':>8} Reason")
    print(f"  {'-'*8} {'-'*9} {'-'*8} {'-'*50}")

    for sym, info in sorted(symbols.items()):
        print(
            f"  {sym:<8} "
            f"{str(info.get('recommendation')):<9} "
            f"{str(info.get('min_setup_score')):>8} "
            f"{(info.get('reason') or '')[:100]}"
        )


def section_missed_opportunity(missed):
    print_header("Missed opportunity memory")

    if not missed:
        print("  No missed_opportunity_memory.json available.")
        return

    print(f"  generated_at          : {missed.get('generated_at')}")
    print(f"  date                  : {missed.get('date')}")
    print(f"  signals_analyzed      : {missed.get('signals_analyzed')}")
    print(f"  signals_with_bar_data : {missed.get('signals_with_bar_data')}")

    category_memory = missed.get("category_memory") or {}

    review = top_items(
        category_memory,
        predicate=lambda k, v: v.get("recommendation") in ("review_too_strict", "keep_strict"),
        sort_key=lambda k, v: (
            {"review_too_strict": 0, "keep_strict": 1}.get(v.get("recommendation"), 9),
            -float(v.get("signals") or 0),
        ),
        limit=15,
    )

    print()
    print("  Rejection gate readout:")
    print(f"  {'Category':<28} {'Rec':<18} {'N':>4} {'Missed%':>8} {'GoodRej%':>9} {'Avg30m':>8} Reason")
    print(f"  {'-'*28} {'-'*18} {'-'*4} {'-'*8} {'-'*9} {'-'*8} {'-'*40}")

    if not review:
        print("  No gate review signals yet.")
        return

    for cat, info in review:
        print(
            f"  {cat:<28} "
            f"{str(info.get('recommendation')):<18} "
            f"{int(info.get('signals') or 0):>4} "
            f"{float(info.get('missed_good_rate_pct') or 0):>8.1f} "
            f"{float(info.get('good_reject_rate_pct') or 0):>9.1f} "
            f"{float(info.get('avg_30m_return_pct') or 0):>8.3f} "
            f"{(info.get('reason') or '')[:70]}"
        )


def section_excursion(excursion):
    print_header("Excursion / MFE-MAE memory")

    if not excursion:
        print("  No excursion_memory.json available.")
        return

    print(f"  generated_at          : {excursion.get('generated_at')}")
    print(f"  date                  : {excursion.get('date')}")
    print(f"  trades_analyzed       : {excursion.get('trades_analyzed')}")
    print(f"  trades_with_bar_data  : {excursion.get('trades_with_bar_data')}")

    symbol_memory = excursion.get("symbol_memory") or {}
    setup_memory = excursion.get("setup_memory") or {}

    print()
    print("  Symbol excursion warnings:")
    print(f"  {'Symbol':<8} {'Rec':<16} {'N':>4} {'P&L':>10} {'MFE%':>8} {'MAE%':>8} {'Giveback%':>10} Reason")
    print(f"  {'-'*8} {'-'*16} {'-'*4} {'-'*10} {'-'*8} {'-'*8} {'-'*10} {'-'*40}")

    warnings = top_items(
        symbol_memory,
        predicate=lambda k, v: v.get("recommendation") in ("tighten_entries", "improve_exits"),
        sort_key=lambda k, v: (
            {"tighten_entries": 0, "improve_exits": 1}.get(v.get("recommendation"), 9),
            -float(v.get("trades") or 0),
        ),
        limit=15,
    )

    if not warnings:
        print("  No symbol excursion warnings yet.")
    else:
        for sym, info in warnings:
            print(
                f"  {sym:<8} "
                f"{str(info.get('recommendation')):<16} "
                f"{int(info.get('trades') or 0):>4} "
                f"{money(info.get('total_pnl')):>10} "
                f"{float(info.get('avg_mfe_pct') or 0):>8.3f} "
                f"{float(info.get('avg_mae_pct') or 0):>8.3f} "
                f"{float(info.get('avg_profit_giveback_pct') or 0):>10.1f} "
                f"{(info.get('reason') or '')[:70]}"
            )

    print()
    print("  Setup excursion warnings:")
    setup_warnings = top_items(
        setup_memory,
        predicate=lambda k, v: v.get("recommendation") in ("tighten_entries", "improve_exits"),
        sort_key=lambda k, v: (
            {"tighten_entries": 0, "improve_exits": 1}.get(v.get("recommendation"), 9),
            -float(v.get("trades") or 0),
        ),
        limit=15,
    )

    if not setup_warnings:
        print("  No setup excursion warnings yet.")
    else:
        print(f"  {'Setup':<28} {'Rec':<16} {'N':>4} {'P&L':>10} {'Giveback%':>10} Reason")
        print(f"  {'-'*28} {'-'*16} {'-'*4} {'-'*10} {'-'*10} {'-'*40}")
        for setup, info in setup_warnings:
            print(
                f"  {setup:<28} "
                f"{str(info.get('recommendation')):<16} "
                f"{int(info.get('trades') or 0):>4} "
                f"{money(info.get('total_pnl')):>10} "
                f"{float(info.get('avg_profit_giveback_pct') or 0):>10.1f} "
                f"{(info.get('reason') or '')[:70]}"
            )


def section_policy_backtest(policy):
    print_header("Policy backtest summary")

    if not policy:
        print("  No policy_backtest_summary.json available.")
        return

    print(f"  generated_at                 : {policy.get('generated_at')}")
    print(f"  rows_analyzed                : {policy.get('rows_analyzed')}")
    print(f"  actual_approved              : {policy.get('actual_approved')}")
    print(f"  actual_rejected              : {policy.get('actual_rejected')}")
    print(f"  policy_allow                 : {policy.get('policy_allow')}")
    print(f"  policy_size_down             : {policy.get('policy_size_down')}")
    print(f"  policy_block                 : {policy.get('policy_block')}")
    print(f"  policy_would_block_approved  : {policy.get('policy_would_block_approved')}")
    print(f"  policy_would_allow_rejected  : {policy.get('policy_would_allow_rejected')}")
    print(f"  recommendation               : {policy.get('recommendation')}")
    print(f"  reason                       : {policy.get('reason')}")

    by_symbol = policy.get("by_symbol") or {}
    if by_symbol:
        print()
        print("  Symbols most affected by policy blocks:")
        print(f"  {'Symbol':<8} {'Total':>5} {'Allow':>5} {'SizeDn':>6} {'Block':>5}")
        print(f"  {'-'*8} {'-'*5} {'-'*5} {'-'*6} {'-'*5}")

        rows = sorted(
            by_symbol.items(),
            key=lambda kv: int((kv[1] or {}).get("block") or 0),
            reverse=True,
        )[:15]

        for sym, info in rows:
            if int(info.get("block") or 0) <= 0:
                continue
            print(
                f"  {sym:<8} "
                f"{int(info.get('total') or 0):>5} "
                f"{int(info.get('allow') or 0):>5} "
                f"{int(info.get('size_down') or 0):>6} "
                f"{int(info.get('block') or 0):>5}"
            )


def section_recommendations(strategy, missed, excursion, policy):
    print_header("Review recommendations")

    recommendations = []

    if policy and policy.get("recommendation") == "policy_too_strict":
        recommendations.append("Decision policy may be too strict; review approved buys it would have blocked.")
    elif policy and policy.get("recommendation") == "policy_too_loose":
        recommendations.append("Decision policy may be too loose; review rejected buys it would have allowed.")

    if missed:
        cats = missed.get("category_memory") or {}
        for cat, info in cats.items():
            if info.get("recommendation") == "review_too_strict":
                recommendations.append(
                    f"Gate '{cat}' may be too strict: {info.get('reason')}"
                )

    if excursion:
        sym_mem = excursion.get("symbol_memory") or {}
        for sym, info in sym_mem.items():
            if info.get("recommendation") == "tighten_entries":
                recommendations.append(
                    f"{sym}: entry quality may need tightening ({info.get('reason')})"
                )
            elif info.get("recommendation") == "improve_exits":
                recommendations.append(
                    f"{sym}: exits/profit protection may need improvement ({info.get('reason')})"
                )

    if strategy:
        symbols = strategy.get("symbols") or {}
        for sym, info in symbols.items():
            if info.get("recommendation") == "avoid":
                recommendations.append(
                    f"{sym}: strategy memory says avoid; require premium setup or manual review."
                )
            elif info.get("recommendation") == "caution":
                recommendations.append(
                    f"{sym}: strategy memory says caution; min_setup_score={info.get('min_setup_score')}."
                )

    if not recommendations:
        print("  No urgent review items from current memory files.")
        return

    for i, rec in enumerate(recommendations[:25], start=1):
        print(f"  {i:>2}. {rec}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--compact", action="store_true", help="Skip detailed sections")
    args = parser.parse_args()

    loaded = {
        key: load_json(path)
        for key, path in FILES.items()
    }

    strategy = loaded["strategy_memory"][0]
    manual = loaded["manual_overrides"][0]
    missed = loaded["missed_opportunity"][0]
    excursion = loaded["excursion"][0]
    policy = loaded["policy_backtest"][0]

    print("=" * 80)
    print("  Strategy Brain Report")
    print("=" * 80)

    section_file_status(loaded)
    section_strategy_memory(strategy)
    section_policy_backtest(policy)

    if not args.compact:
        section_manual_overrides(manual)
        section_missed_opportunity(missed)
        section_excursion(excursion)

    section_recommendations(strategy, missed, excursion, policy)


if __name__ == "__main__":
    main()
