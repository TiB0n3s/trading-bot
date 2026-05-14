import sys
import sqlite3
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path
from collections import defaultdict
from datetime import date, timedelta
from trade_matcher import rebuild_matched_trades

from db import DB_PATH, get_connection
LOG_PATH = Path(__file__).parent / "daily_summary.log"

# claude-haiku-4-5-20251001 pricing (per million tokens)
HAIKU_INPUT_CPM  = 0.80
HAIKU_OUTPUT_CPM = 4.00
AVG_INPUT_TOKENS  = 550
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

def _query_matched(con, extra_where, params):
    """Fetch matched_trades for a date predicate on exit_timestamp.

    `extra_where` is appended to a base 'WHERE 1=1' so it must start with ' AND '.
    Returns an empty list if matched_trades doesn't exist (graceful degrade).
    """
    try:
        return con.execute(f"""
            SELECT symbol, qty, entry_price, exit_price, realized_pnl, won
            FROM matched_trades
            WHERE 1=1 {extra_where}
            ORDER BY exit_timestamp ASC
        """, params).fetchall()
    except sqlite3.OperationalError:
        return []

def _load_trade_rows(con, target_date: str = None, start_date: str = None, end_date: str = None):
    if target_date:
        return con.execute(
            """
            SELECT
                id,
                timestamp,
                symbol,
                action,
                approved,
                rejection_reason,
                confidence,
                setup_label,
                setup_policy_action,
                setup_policy_reason
            FROM trades
            WHERE timestamp LIKE ?
            ORDER BY timestamp ASC
            """,
            (f"{target_date}%",),
        ).fetchall()

    if start_date and end_date:
        return con.execute(
            """
            SELECT
                id,
                timestamp,
                symbol,
                action,
                approved,
                rejection_reason,
                confidence,
                setup_label,
                setup_policy_action,
                setup_policy_reason
            FROM trades
            WHERE timestamp >= ? AND timestamp < ?
            ORDER BY timestamp ASC
            """,
            (start_date, end_date),
        ).fetchall()

    return []


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
                f"{row['approval_rate']:.1f}%"
                if row.get("approval_rate") is not None
                else "-",
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
        "setup_policy": "Entry quality / setup policy",
        "addon_momentum_gate": "Add-on momentum gate",
        "session_momentum_gate": "Session momentum gate",
        "prediction_gate": "Prediction gate",
        "confidence_gate": "Low confidence (Claude)",
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

def _render(rows, matched, header, trade_rows=None):
    lines = []
    def p(*args):
        line = " ".join(str(a) for a in args)
        lines.append(line)
        print(line)

    p(f"\n{'='*60}")
    p(f"  {header}")
    p(f"{'='*60}")

    # ── 1. Signal overview ────────────────────────────────────────
    total     = len(rows)
    approved  = [r for r in rows if r["approved"]]
    rejected  = [r for r in rows if not r["approved"]]
    apr_rate  = 100 * len(approved) / total if total else 0

    p(f"\n── SIGNALS ──────────────────────────────────────────────")
    p(f"  Total received : {total}")
    p(f"  Approved       : {len(approved)}  ({apr_rate:.0f}%)")
    p(f"  Rejected       : {len(rejected)}  ({100-apr_rate:.0f}%)")

    # Map known category prefixes (introduced in Stage 5 of the rejection-logging
    # refactor) to friendly bucket names. Legacy / Claude-verbose rejections that
    # don't have a recognizable prefix fall through to substring matching.
    PREFIX_BUCKETS = {
        "market_hours":         "Outside trading hours",
        "duplicate_webhook":    "Duplicate webhook",
        "symbol_override":      "Symbol override",
        "circuit_breaker":      "Daily loss limit",
        "ghost_sell":           "Ghost sell (no Alpaca position)",
        "cooldown":             "Cooldown active",
        "churn_window":         "Sell→buy churn (time)",
        "churn_price":          "Sell→buy churn (price)",
        "exposure_cap":         "Per-symbol exposure cap (4%)",
        "daily_symbol_buy_limit": "Daily symbol buy limit",
        "correlation_cap":      "Cluster exposure cap",
        "trend_gate":           "Trend gate (neutral/bearish)",
        "fundamental_score":    "Fundamental score gate",
        "macro_risk":           "Macro risk (capital preservation)",
        "macro_position_limit": "Macro position limit",
        "market_bias_avoid":    "Brief flagged 'avoid'",
        "soft_avoid_prediction_gate": "Soft avoid prediction gate",
        "live_bias_downgrade": "Live bias downgrade",
        "chase_prevention":     "Chase prevention (do_not_chase)",
        "confidence_gate":      "Low confidence (Claude)",
        "entry_quality":        "Entry quality / pullback requirement",
    }

    import re as _re
    _prefix_re = _re.compile(r'^([a-z_]+):')

    reason_counts = defaultdict(int)
    for r in rejected:
        bucket = _bucket_rejection_reason(r["rejection_reason"])
        reason_counts[bucket] += 1
        
    p(f"\n  Rejection breakdown:")
    reason_counts = defaultdict(int)
    for r in rejected:
        bucket = _bucket_rejection_reason(r["rejection_reason"])
        reason_counts[bucket] += 1

    for bucket, cnt in sorted(reason_counts.items(), key=lambda x: -x[1]):
        p(f"    {cnt:>4}  {bucket}")

    # Session momentum gate summary
    session_gate_rejected = [
        r for r in rejected
        if str(r["rejection_reason"] or "").startswith("session_momentum_gate:")
    ]

    p(f"\n── SESSION MOMENTUM GATE ─────────────────────────────────")
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
    p(f"\n── ORDERS BY SYMBOL ─────────────────────────────────────")
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
    p(f"\n── REALIZED P&L (from matched_trades) ───────────────────")

    if matched:
        sym_pnl = defaultdict(float)
        sym_count = defaultdict(int)
        for m in matched:
            sym_pnl[m["symbol"]]   += m["realized_pnl"]
            sym_count[m["symbol"]] += 1
        total_pnl = sum(sym_pnl.values())

        p(f"  {'Symbol':<6}  {'P&L':>10}  {'Trades':>6}")
        p(f"  {'------':<6}  {'----------':>10}  {'------':>6}")
        for sym, pnl in sorted(sym_pnl.items(), key=lambda x: -x[1]):
            tag = "+" if pnl >= 0 else ""
            p(f"  {sym:<6}  {tag}{pnl:>9.2f}  {sym_count[sym]:>6}")
        p(f"  {'------':<6}  {'----------':>10}  {'------':>6}")
        p(f"  {'TOTAL':<6}  {('+' if total_pnl>=0 else '')}{total_pnl:>9.2f}  {len(matched):>6}")

        # ── 4. Win rate + profit factor + expectancy ──────────────
        wins   = [m for m in matched if m["realized_pnl"] > 0]
        losses = [m for m in matched if m["realized_pnl"] < 0]
        flats  = [m for m in matched if m["realized_pnl"] == 0]
        n      = len(matched)
        win_rate = 100 * len(wins) / n if n else 0
        gross_profit = sum(m["realized_pnl"] for m in wins)
        gross_loss   = abs(sum(m["realized_pnl"] for m in losses))
        if gross_loss > 0:
            pf_str = f"{gross_profit / gross_loss:.2f}"
        elif gross_profit > 0:
            pf_str = "∞ (no losses)"
        else:
            pf_str = "—"
        expectancy = total_pnl / n if n else 0

        p(f"\n── WIN RATE & PROFIT FACTOR ─────────────────────────────")
        p(f"  Matched trades : {n}")
        p(f"  Wins           : {len(wins)}  ({win_rate:.0f}%)")
        p(f"  Losses         : {len(losses)}")
        p(f"  Flat           : {len(flats)}")
        p(f"  Gross profit   : ${gross_profit:.2f}")
        p(f"  Gross loss     : ${gross_loss:.2f}")
        p(f"  Profit factor  : {pf_str}")
        p(f"  Expectancy     : ${expectancy:+.2f} per matched trade")

        # ── 5. Best / worst ──────────────────────────────────────
        best  = max(matched, key=lambda m: m["realized_pnl"])
        worst = min(matched, key=lambda m: m["realized_pnl"])
        p(f"\n── BEST / WORST TRADES ───────────────────────────────────")
        tag_b = "+" if best["realized_pnl"] >= 0 else ""
        p(f"  Best  : {best['symbol']}  {best['qty']} shares  "
          f"buy={best['entry_price']:.2f} sell={best['exit_price']:.2f}  "
          f"P&L={tag_b}{best['realized_pnl']:.2f}")
        p(f"  Worst : {worst['symbol']}  {worst['qty']} shares  "
          f"buy={worst['entry_price']:.2f} sell={worst['exit_price']:.2f}  "
          f"P&L={worst['realized_pnl']:.2f}")
    else:
        p("  No matched buy/sell pairs found for this period.")

    # ── 6. Claude API cost estimate ───────────────────────────────
    p(f"\n── CLAUDE API USAGE (est.) ───────────────────────────────")
    api_calls   = total
    input_cost  = api_calls * AVG_INPUT_TOKENS  / 1_000_000 * HAIKU_INPUT_CPM
    output_cost = api_calls * AVG_OUTPUT_TOKENS / 1_000_000 * HAIKU_OUTPUT_CPM
    total_cost  = input_cost + output_cost
    p(f"  Est. API calls : {api_calls}")
    p(f"  Est. tokens    : {api_calls * AVG_INPUT_TOKENS:,} in / {api_calls * AVG_OUTPUT_TOKENS:,} out")
    p(f"  Est. cost      : ${total_cost:.4f}  (Haiku @ $0.80/$4.00 per MTok)")

    # ── 7. Live execution / setup-policy monitoring ─────────────────
    trade_rows = trade_rows or rows
    buy_trade_rows = [r for r in trade_rows if (r["action"] or "").lower() == "buy"]
    block_trade_rows = [
        r for r in buy_trade_rows
        if (r["rejection_reason"] or "").startswith("setup_policy:")
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

    p(f"\n── LIVE EXECUTION ───────────────────────────────────────")
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
    print_trade_table(p, "Live BUYs by Rejection Category", live_buys_by_rejection_category, limit=10)

    if block_trade_rows:
        print_trade_table(p, "Setup Policy Blocks by Setup Label", setup_policy_blocks_by_label, limit=10)
        print_trade_table(p, "Setup Policy Blocks by Policy Reason", setup_policy_blocks_by_reason, limit=10)
    else:
        p()
        p("── Setup Policy Blocks ─────────────────────────────────")
        p("No setup-policy blocks for this period.")

    p(f"\n{'='*60}\n")

    with open(LOG_PATH, "a") as f:
        f.write("\n".join(lines) + "\n")


def _refresh_matched():
    try:
        rebuild_matched_trades()
    except Exception as e:
        print(f"WARNING: matched_trades rebuild failed: {e}")


def run(target_date: str = None):
    target_date = target_date or str(date.today())
    _refresh_matched()
    con = get_connection(DB_PATH)
    rows = con.execute(
        "SELECT * FROM trades WHERE timestamp LIKE ?", (f"{target_date}%",)
    ).fetchall()
    trade_rows = _load_trade_rows(con, target_date=target_date)
    matched = _query_matched(con, "AND exit_timestamp LIKE ?", (f"{target_date}%",))
    con.close()
    _render(rows, matched, f"DAILY SUMMARY — {target_date}", trade_rows=trade_rows)


def run_week(target_date: str = None):
    if target_date:
        ref = date.fromisoformat(target_date)
    else:
        today = date.today()
        if today.weekday() >= 5:
            ref = today - timedelta(days=today.weekday() - 4)
        else:
            ref = today

    monday = ref - timedelta(days=ref.weekday())
    friday = monday + timedelta(days=4)
    end_excl = (friday + timedelta(days=1)).isoformat()

    _refresh_matched()
    con = get_connection(DB_PATH)
    rows = con.execute(
        "SELECT * FROM trades WHERE timestamp >= ? AND timestamp < ?",
        (monday.isoformat(), end_excl),
    ).fetchall()
    trade_rows = _load_trade_rows(
        con,
        start_date=monday.isoformat(),
        end_date=end_excl,
    )
    matched = _query_matched(
        con,
        "AND exit_timestamp >= ? AND exit_timestamp < ?",
        (monday.isoformat(), end_excl),
    )
    con.close()
    _render(
        rows,
        matched,
        f"WEEKLY SUMMARY — {monday} to {friday}",
        trade_rows=trade_rows,
    )


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--week":
        run_week(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        run(sys.argv[1] if len(sys.argv) > 1 else None)
