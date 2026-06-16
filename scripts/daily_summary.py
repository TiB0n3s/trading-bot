import sys
from collections import defaultdict
from pathlib import Path

from services.daily_summary_service import build_default_daily_summary_service

LOG_PATH = Path(__file__).parent / "daily_summary.log"

# claude-haiku-4-5-20251001 pricing (per million tokens)
HAIKU_INPUT_CPM = 0.80
HAIKU_OUTPUT_CPM = 4.00
AVG_INPUT_TOKENS = 550
AVG_OUTPUT_TOKENS = 125


def summarize_trade_rows(rows):
    if not rows:
        return {
            "count": 0,
            "approved_count": 0,
            "rejected_count": 0,
            "approval_rate": None,
        }

    approved_count = sum(1 for r in rows if int(r["approved"] or 0) == 1)
    rejected_count = len(rows) - approved_count

    return {
        "count": len(rows),
        "approved_count": approved_count,
        "rejected_count": rejected_count,
        "approval_rate": (approved_count / len(rows) * 100.0) if rows else None,
    }


def grouped_trade_summary(rows, key_fn, min_samples: int = 1):
    groups = defaultdict(list)
    for row in rows:
        groups[key_fn(row)].append(row)

    out = []
    for key, group_rows in groups.items():
        if len(group_rows) < min_samples:
            continue

        summary = summarize_trade_rows(group_rows)
        summary["group"] = key
        out.append(summary)

    out.sort(
        key=lambda x: (
            x["count"],
            x["approval_rate"] if x["approval_rate"] is not None else -1,
        ),
        reverse=True,
    )
    return out


def _grouped_trade_summary(rows, key_fn, min_samples: int = 1):
    groups = defaultdict(list)
    for row in rows:
        groups[key_fn(row)].append(row)

    out = []
    for key, group_rows in groups.items():
        if len(group_rows) < min_samples:
            continue

        summary = summarize_trade_rows(group_rows)
        summary["group"] = key
        out.append(summary)

    out.sort(
        key=lambda x: (
            x["count"],
            x["approval_rate"] if x["approval_rate"] is not None else -1,
        ),
        reverse=True,
    )
    return out


def print_trade_table(p, title: str, rows: list[dict], limit: int = 10):
    p()
    p("── " + title + " " + "─" * max(1, 70 - len(title)))

    if not rows:
        p("No rows.")
        return

    headers = ["Group", "Count", "Approved", "Rejected", "Approval%"]
    widths = [42, 7, 9, 9, 10]
    fmt = " ".join(f"{{:<{w}}}" for w in widths)

    p(fmt.format(*headers))
    p(fmt.format(*["-" * w for w in widths]))

    for row in rows[:limit]:
        p(
            fmt.format(
                str(row.get("group", ""))[:42],
                row.get("count", 0),
                row.get("approved_count", 0),
                row.get("rejected_count", 0),
                f"{row['approval_rate']:.1f}%" if row.get("approval_rate") is not None else "-",
            )
        )


def print_auto_buy_hard_block_audit(p, audit: dict | None):
    audit = audit or {}
    p()
    p("── AUTO-BUY HARD BLOCK AUDIT ───────────────────────────")
    p("  Purpose         : measure blocked counterfactuals before changing any gate")
    p("  Pulling         : saved auto-buy decision snapshots and candidate JSON")
    p("  Counterfactual  : decision_without_hard_blocks, score, blocker, setup, regime")
    p(
        "  Action plan     : keep blocks until forward outcomes prove a block rejects positive net EV"
    )
    p("  Runtime effect  : observe-only diagnostics; no trade authority")

    rows_seen = int(audit.get("rows_seen") or 0)
    hard_blocked = int(audit.get("hard_blocked_rows") or 0)
    counterfactual_strong = int(audit.get("counterfactual_strong_rows") or 0)
    counterfactual_watch = int(audit.get("counterfactual_watch_rows") or 0)
    p(f"  Snapshots read  : {rows_seen}")
    p(f"  Hard-blocked    : {hard_blocked}")
    p(f"  Would-be strong : {counterfactual_strong}")
    p(f"  Would-be watch  : {counterfactual_watch}")

    by_reason = audit.get("by_reason") or []
    if by_reason:
        p()
        p("  Blocker summary:")
        headers = ["Blocker", "Rows", "WouldStrong", "WouldWatch", "AvgScore", "MaxScore"]
        widths = [34, 6, 12, 10, 9, 9]
        fmt = " ".join(f"{{:<{w}}}" for w in widths)
        p("  " + fmt.format(*headers))
        p("  " + fmt.format(*["-" * w for w in widths]))
        for row in by_reason[:10]:
            avg_score = row.get("avg_score")
            max_score = row.get("max_score")
            p(
                "  "
                + fmt.format(
                    str(row.get("reason") or "unknown")[:34],
                    row.get("rows", 0),
                    row.get("counterfactual_strong_rows", 0),
                    row.get("counterfactual_watch_rows", 0),
                    f"{avg_score:.1f}" if avg_score is not None else "-",
                    f"{max_score:.1f}" if max_score is not None else "-",
                )
            )
    else:
        p("  Blocker summary : no hard-block rows captured.")

    top_rows = audit.get("top_counterfactual_strong") or []
    if top_rows:
        p()
        p("  Top would-be strong candidates rejected by hard blocks:")
        headers = ["Time", "Sym", "Score", "Blocker", "Final"]
        widths = [19, 6, 7, 34, 12]
        fmt = " ".join(f"{{:<{w}}}" for w in widths)
        p("  " + fmt.format(*headers))
        p("  " + fmt.format(*["-" * w for w in widths]))
        for row in top_rows[:8]:
            p(
                "  "
                + fmt.format(
                    str(row.get("timestamp") or "")[:19],
                    str(row.get("symbol") or "")[:6],
                    f"{row.get('score'):.1f}" if row.get("score") is not None else "-",
                    str(row.get("primary_reason") or "unknown")[:34],
                    str(row.get("final_decision") or "-")[:12],
                )
            )


def _bucket_rejection_reason(reason: str | None) -> str:
    PREFIX_BUCKETS = {
        "market_hours": "Outside trading hours",
        "stale_signal": "Stale signal",
        "duplicate_webhook": "Duplicate webhook",
        "symbol_override": "Symbol override",
        "circuit_breaker": "Daily loss limit",
        "ghost_sell": "Ghost sell (no Alpaca position)",
        "cooldown": "Cooldown active",
        "churn_window": "Sell→buy churn (time)",
        "churn_price": "Sell→buy churn (price)",
        "exposure_cap": "Per-symbol exposure cap (4%)",
        "daily_symbol_buy_limit": "Daily symbol buy limit",
        "session_trade_count": "Session trade-count gate",
        "correlation_cap": "Cluster exposure cap",
        "fundamental_score": "Fundamental score gate",
        "trend_gate": "Trend gate (neutral/bearish)",
        "trend_confirmation": "Trend confirmation",
        "macro_risk": "Macro risk",
        "macro_position_limit": "Macro position limit",
        "market_bias_avoid": "Brief flagged 'avoid'",
        "soft_avoid_prediction_gate": "Soft avoid prediction gate",
        "live_bias_downgrade": "Live bias downgrade",
        "chase_prevention": "Chase prevention",
        "late_after_quote_delay": "Late after quote delay",
        "setup_policy": "Entry quality / setup policy",
        "addon_momentum_gate": "Add-on momentum gate",
        "session_momentum_gate": "Session momentum gate",
        "prediction_gate": "Prediction gate",
        "strategy_memory": "Strategy memory gate",
        "decision_policy": "Decision policy gate",
        "confidence_gate": "Low confidence (Claude)",
        "claude_parse_error": "Claude parse error",
        "claude_engine_error": "Claude engine/timeout error",
        "entry_quality": "Entry quality / pullback requirement",
        "second_look": "Second-look market check",
        "cash_safe_symbol": "Cash-safe symbol block",
        "cash_safe_position_limit": "Cash-safe position limit",
        "cash_safe_daily_symbol_limit": "Cash-safe daily symbol limit",
        "cash_safe_confidence": "Cash-safe confidence gate",
        "order_path_exception": "Order path exception",
    }

    import re as _re

    prefix_re = _re.compile(r"^([a-z_]+):")

    reason = reason or "unknown"
    m = prefix_re.match(reason)
    if m and m.group(1) in PREFIX_BUCKETS:
        return PREFIX_BUCKETS[m.group(1)]

    rl = reason.lower()

    if "entry quality" in rl or "pullback" in rl:
        return "Entry quality / pullback requirement"
    if "already" in rl or "concentration" in rl or "existing" in rl:
        return "Position already open / concentration risk"
    if "max" in rl and "position" in rl:
        return "Max position limit reached"
    if "parse error" in rl or "engine error" in rl:
        return "Parse / engine error"
    if "outside" in rl or "time" in rl or "hours" in rl:
        return "Outside trading hours"
    if "loss limit" in rl or "daily" in rl:
        return "Daily loss limit"
    if "source" in rl:
        return "Invalid signal source"
    if "short" in rl or "conflict" in rl or "direction" in rl:
        return "Conflicting position direction"

    return "Other (Claude verbose)"


def _render(rows, matched, header, trade_rows=None, auto_buy_hard_block_audit=None):
    lines = []

    def p(*args):
        line = " ".join(str(a) for a in args)
        lines.append(line)
        print(line)

    p(f"\n{'=' * 60}")
    p(f"  {header}")
    p(f"{'=' * 60}")

    # ── 1. Signal overview ────────────────────────────────────────
    total = len(rows)
    approved = [r for r in rows if r["approved"]]
    rejected = [r for r in rows if not r["approved"]]
    apr_rate = 100 * len(approved) / total if total else 0

    p("\n── SIGNALS ──────────────────────────────────────────────")
    p(f"  Total received : {total}")
    p(f"  Approved       : {len(approved)}  ({apr_rate:.0f}%)")
    p(f"  Rejected       : {len(rejected)}  ({100 - apr_rate:.0f}%)")

    reason_counts = defaultdict(int)
    for r in rejected:
        bucket = _bucket_rejection_reason(r["rejection_reason"])
        reason_counts[bucket] += 1

    p("\n  Rejection breakdown:")
    for bucket, cnt in sorted(reason_counts.items(), key=lambda x: -x[1]):
        p(f"    {cnt:>4}  {bucket}")

    # ── 1b. Actionable signal overview ─────────────────────────────
    # This removes expected/no-op noise so the live trading quality is easier
    # to evaluate. It does not change trading behavior.
    NON_ACTIONABLE_BUCKETS = {
        "Ghost sell (no Alpaca position)",
        "Outside trading hours",
        "Duplicate webhook",
        "Stale signal",
    }

    actionable_rows = []
    excluded_noise_counts = defaultdict(int)

    for r in rows:
        if r["approved"]:
            actionable_rows.append(r)
            continue

        bucket = _bucket_rejection_reason(r["rejection_reason"])
        if bucket in NON_ACTIONABLE_BUCKETS:
            excluded_noise_counts[bucket] += 1
        else:
            actionable_rows.append(r)

    actionable_total = len(actionable_rows)
    actionable_approved = [r for r in actionable_rows if r["approved"]]
    actionable_rejected = [r for r in actionable_rows if not r["approved"]]
    actionable_apr_rate = (
        100 * len(actionable_approved) / actionable_total if actionable_total else 0
    )

    p("\n── ACTIONABLE SIGNALS ───────────────────────────────────")
    p(f"  Total actionable : {actionable_total}")
    p(f"  Approved         : {len(actionable_approved)}  ({actionable_apr_rate:.1f}%)")
    p(f"  Rejected         : {len(actionable_rejected)}  ({100 - actionable_apr_rate:.1f}%)")

    if excluded_noise_counts:
        p("\n  Excluded noise:")
        for bucket, cnt in sorted(excluded_noise_counts.items(), key=lambda x: -x[1]):
            p(f"    {cnt:>4}  {bucket}")

    # Session momentum gate summary
    session_gate_rejected = [
        r for r in rejected if str(r["rejection_reason"] or "").startswith("session_momentum_gate:")
    ]

    p("\n── SESSION MOMENTUM GATE ─────────────────────────────────")
    if not session_gate_rejected:
        p("  No session momentum gate rejections.")
    else:
        label_counts = defaultdict(int)
        symbol_counts = defaultdict(int)

        for r in session_gate_rejected:
            label_counts[r["session_trend_label"] or "unknown"] += 1
            symbol_counts[r["symbol"] or "unknown"] += 1

        p("  By session label:")
        for label, cnt in sorted(label_counts.items(), key=lambda x: -x[1]):
            p(f"    {cnt:>4}  {label}")

        p("  By symbol:")
        for sym, cnt in sorted(symbol_counts.items(), key=lambda x: -x[1])[:10]:
            p(f"    {cnt:>4}  {sym}")

    # ── 2. Orders placed vs null by symbol ───────────────────────
    p("\n── ORDERS BY SYMBOL ─────────────────────────────────────")
    sym_data = defaultdict(lambda: {"approved": 0, "with_order": 0, "null_order": 0})
    for r in approved:
        sym = r["symbol"]
        sym_data[sym]["approved"] += 1
        if r["order_id"]:
            sym_data[sym]["with_order"] += 1
        else:
            sym_data[sym]["null_order"] += 1

    p(f"  {'Symbol':<6}  {'Approved':>8}  {'Orders':>7}  {'Null':>6}")
    p(f"  {'------':<6}  {'--------':>8}  {'-------':>7}  {'----':>6}")
    for sym, d in sorted(sym_data.items()):
        p(f"  {sym:<6}  {d['approved']:>8}  {d['with_order']:>7}  {d['null_order']:>6}")

    # ── 3. Realized P&L (from matched_trades) ────────────────────
    p("\n── REALIZED P&L (from matched_trades) ───────────────────")

    if matched:
        sym_pnl = defaultdict(float)
        sym_count = defaultdict(int)
        for m in matched:
            sym_pnl[m["symbol"]] += m["realized_pnl"]
            sym_count[m["symbol"]] += 1
        total_pnl = sum(sym_pnl.values())

        p(f"  {'Symbol':<6}  {'P&L':>10}  {'Trades':>6}")
        p(f"  {'------':<6}  {'----------':>10}  {'------':>6}")
        for sym, pnl in sorted(sym_pnl.items(), key=lambda x: -x[1]):
            tag = "+" if pnl >= 0 else ""
            p(f"  {sym:<6}  {tag}{pnl:>9.2f}  {sym_count[sym]:>6}")
        p(f"  {'------':<6}  {'----------':>10}  {'------':>6}")
        p(f"  {'TOTAL':<6}  {('+' if total_pnl >= 0 else '')}{total_pnl:>9.2f}  {len(matched):>6}")

        # ── 4. Win rate + profit factor + expectancy ──────────────
        wins = [m for m in matched if m["realized_pnl"] > 0]
        losses = [m for m in matched if m["realized_pnl"] < 0]
        flats = [m for m in matched if m["realized_pnl"] == 0]
        n = len(matched)
        win_rate = 100 * len(wins) / n if n else 0
        gross_profit = sum(m["realized_pnl"] for m in wins)
        gross_loss = abs(sum(m["realized_pnl"] for m in losses))
        if gross_loss > 0:
            pf_str = f"{gross_profit / gross_loss:.2f}"
        elif gross_profit > 0:
            pf_str = "∞ (no losses)"
        else:
            pf_str = "—"
        expectancy = total_pnl / n if n else 0

        p("\n── WIN RATE & PROFIT FACTOR ─────────────────────────────")
        p(f"  Matched trades : {n}")
        p(f"  Wins           : {len(wins)}  ({win_rate:.0f}%)")
        p(f"  Losses         : {len(losses)}")
        p(f"  Flat           : {len(flats)}")
        p(f"  Gross profit   : ${gross_profit:.2f}")
        p(f"  Gross loss     : ${gross_loss:.2f}")
        p(f"  Profit factor  : {pf_str}")
        p(f"  Expectancy     : ${expectancy:+.2f} per matched trade")

        # ── 5. Best / worst ──────────────────────────────────────
        best = max(matched, key=lambda m: m["realized_pnl"])
        worst = min(matched, key=lambda m: m["realized_pnl"])
        p("\n── BEST / WORST TRADES ───────────────────────────────────")
        tag_b = "+" if best["realized_pnl"] >= 0 else ""
        p(
            f"  Best  : {best['symbol']}  {best['qty']} shares  "
            f"buy={best['entry_price']:.2f} sell={best['exit_price']:.2f}  "
            f"P&L={tag_b}{best['realized_pnl']:.2f}"
        )
        p(
            f"  Worst : {worst['symbol']}  {worst['qty']} shares  "
            f"buy={worst['entry_price']:.2f} sell={worst['exit_price']:.2f}  "
            f"P&L={worst['realized_pnl']:.2f}"
        )
    else:
        p("  No matched buy/sell pairs found for this period.")

    # ── 6. Claude API cost estimate ───────────────────────────────
    p("\n── CLAUDE API USAGE (est.) ───────────────────────────────")
    api_calls = total
    input_cost = api_calls * AVG_INPUT_TOKENS / 1_000_000 * HAIKU_INPUT_CPM
    output_cost = api_calls * AVG_OUTPUT_TOKENS / 1_000_000 * HAIKU_OUTPUT_CPM
    total_cost = input_cost + output_cost
    p(f"  Est. API calls : {api_calls}")
    p(
        f"  Est. tokens    : {api_calls * AVG_INPUT_TOKENS:,} in / {api_calls * AVG_OUTPUT_TOKENS:,} out"
    )
    p(f"  Est. cost      : ${total_cost:.4f}  (Haiku @ $0.80/$4.00 per MTok)")

    # ── 7. Live execution / setup-policy monitoring ─────────────────
    trade_rows = trade_rows or rows
    buy_trade_rows = [r for r in trade_rows if (r["action"] or "").lower() == "buy"]
    block_trade_rows = [
        r for r in buy_trade_rows if (r["rejection_reason"] or "").startswith("setup_policy:")
    ]

    live_overall = summarize_trade_rows(trade_rows)
    live_buy_overall = summarize_trade_rows(buy_trade_rows)

    live_buys_by_setup_label = grouped_trade_summary(
        buy_trade_rows,
        lambda r: r["setup_label"] or "unknown",
        min_samples=1,
    )
    live_buys_by_setup_policy = grouped_trade_summary(
        buy_trade_rows,
        lambda r: r["setup_policy_action"] or "unknown",
        min_samples=1,
    )
    live_buys_by_rejection_category = grouped_trade_summary(
        buy_trade_rows,
        lambda r: (
            _bucket_rejection_reason(r["rejection_reason"])
            if int(r["approved"] or 0) == 0
            else "approved"
        ),
        min_samples=1,
    )
    setup_policy_blocks_by_label = grouped_trade_summary(
        block_trade_rows,
        lambda r: r["setup_label"] or "unknown",
        min_samples=1,
    )
    setup_policy_blocks_by_reason = grouped_trade_summary(
        block_trade_rows,
        lambda r: r["setup_policy_reason"] or "unknown",
        min_samples=1,
    )

    p("\n── LIVE EXECUTION ───────────────────────────────────────")
    p(f"  Trade rows        : {live_overall['count']}")
    p(f"  Approved          : {live_overall['approved_count']}")
    p(f"  Rejected          : {live_overall['rejected_count']}")
    p(
        f"  Approval rate     : {live_overall['approval_rate']:.1f}%"
        if live_overall["approval_rate"] is not None
        else "  Approval rate     : -"
    )
    p(f"  BUY rows          : {live_buy_overall['count']}")
    p(f"  BUY approved      : {live_buy_overall['approved_count']}")
    p(f"  BUY rejected      : {live_buy_overall['rejected_count']}")
    p(
        f"  BUY approval rate : {live_buy_overall['approval_rate']:.1f}%"
        if live_buy_overall["approval_rate"] is not None
        else "  BUY approval rate : -"
    )

    print_trade_table(p, "Live BUYs by Setup Label", live_buys_by_setup_label, limit=10)
    print_trade_table(p, "Live BUYs by Setup Policy Action", live_buys_by_setup_policy, limit=10)
    print_trade_table(
        p, "Live BUYs by Rejection Category", live_buys_by_rejection_category, limit=10
    )

    if block_trade_rows:
        print_trade_table(
            p, "Setup Policy Blocks by Setup Label", setup_policy_blocks_by_label, limit=10
        )
        print_trade_table(
            p, "Setup Policy Blocks by Policy Reason", setup_policy_blocks_by_reason, limit=10
        )
    else:
        p()
        p("── Setup Policy Blocks ─────────────────────────────────")
        p("No setup-policy blocks for this period.")

    print_auto_buy_hard_block_audit(p, auto_buy_hard_block_audit)

    p(f"\n{'=' * 60}\n")

    with open(LOG_PATH, "a") as f:
        f.write("\n".join(lines) + "\n")


def run(target_date: str = None):
    payload = build_default_daily_summary_service(warning_sink=print).daily_payload(target_date)
    _render(
        payload.rows,
        payload.matched,
        payload.header,
        trade_rows=payload.trade_rows,
        auto_buy_hard_block_audit=payload.auto_buy_hard_block_audit,
    )


def run_week(target_date: str = None):
    payload = build_default_daily_summary_service(warning_sink=print).weekly_payload(target_date)
    _render(
        payload.rows,
        payload.matched,
        payload.header,
        trade_rows=payload.trade_rows,
        auto_buy_hard_block_audit=payload.auto_buy_hard_block_audit,
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--week":
        run_week(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        run(sys.argv[1] if len(sys.argv) > 1 else None)


# Position manager exit categories:
# - position_manager_partial_exit
# - position_manager_full_exit
