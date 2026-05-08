import sqlite3
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

from trade_matcher import rebuild_matched_trades

DB_PATH = Path(__file__).parent / "trades.db"
LOG_PATH = Path(__file__).parent / "daily_summary.log"

# claude-haiku-4-5-20251001 pricing (per million tokens)
HAIKU_INPUT_CPM  = 0.80
HAIKU_OUTPUT_CPM = 4.00
AVG_INPUT_TOKENS  = 550
AVG_OUTPUT_TOKENS = 125


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


def _render(rows, matched, header):
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
        "macro_risk":           "Macro risk (capital preservation)",
        "macro_position_limit": "Macro position limit",
        "market_bias_avoid":    "Brief flagged 'avoid'",
        "chase_prevention":     "Chase prevention (do_not_chase)",
        "confidence_gate":      "Low confidence (Claude)",
    }

    import re as _re
    _prefix_re = _re.compile(r'^([a-z_]+):')

    reason_counts = defaultdict(int)
    for r in rejected:
        reason = r["rejection_reason"] or "unknown"
        m = _prefix_re.match(reason)
        if m and m.group(1) in PREFIX_BUCKETS:
            bucket = PREFIX_BUCKETS[m.group(1)]
        else:
            rl = reason.lower()
            if "already" in rl or "concentration" in rl or "existing" in rl:
                bucket = "Position already open / concentration risk"
            elif "max" in rl and "position" in rl:
                bucket = "Max position limit reached"
            elif "parse error" in rl or "engine error" in rl:
                bucket = "Parse / engine error"
            elif "outside" in rl or "time" in rl or "hours" in rl:
                bucket = "Outside trading hours"
            elif "loss limit" in rl or "daily" in rl:
                bucket = "Daily loss limit"
            elif "source" in rl:
                bucket = "Invalid signal source"
            elif "short" in rl or "conflict" in rl or "direction" in rl:
                bucket = "Conflicting position direction"
            else:
                bucket = "Other (Claude verbose)"
        reason_counts[bucket] += 1

    p(f"\n  Rejection breakdown:")
    for bucket, cnt in sorted(reason_counts.items(), key=lambda x: -x[1]):
        p(f"    {cnt:>4}  {bucket}")

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
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM trades WHERE timestamp LIKE ?", (f"{target_date}%",)
    ).fetchall()
    matched = _query_matched(con, "AND exit_timestamp LIKE ?", (f"{target_date}%",))
    con.close()
    _render(rows, matched, f"DAILY SUMMARY — {target_date}")


def run_week(target_date: str = None):
    if target_date:
        ref = date.fromisoformat(target_date)
    else:
        today = date.today()
        # Weekend: roll back to the just-completed Friday; weekday: use current week
        if today.weekday() >= 5:
            ref = today - timedelta(days=today.weekday() - 4)
        else:
            ref = today

    monday = ref - timedelta(days=ref.weekday())
    friday = monday + timedelta(days=4)
    end_excl = (friday + timedelta(days=1)).isoformat()

    _refresh_matched()
    con = sqlite3.connect(DB_PATH)
    con.row_factory = sqlite3.Row
    rows = con.execute(
        "SELECT * FROM trades WHERE timestamp >= ? AND timestamp < ?",
        (monday.isoformat(), end_excl),
    ).fetchall()
    matched = _query_matched(
        con,
        "AND exit_timestamp >= ? AND exit_timestamp < ?",
        (monday.isoformat(), end_excl),
    )
    con.close()
    _render(rows, matched, f"WEEKLY SUMMARY — {monday} to {friday}")


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--week":
        run_week(sys.argv[2] if len(sys.argv) > 2 else None)
    else:
        run(sys.argv[1] if len(sys.argv) > 1 else None)
