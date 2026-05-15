#!/usr/bin/env python3
"""
Trading bot analytics report — read-only summary across trades.db.

Reads:
  - trades        (signals, decisions, orders, fills)
  - fill_events   (Alpaca event audit trail; introduced in fill_stream Stage 1)
  - rejection_reason category prefixes ('cooldown:', 'trend_gate:', etc.)
  - synthetic_bracket_exit: rows for autonomous bracket-leg exits

No bot behavior changes — just reads.

Usage:
    python analytics_report.py                 # today (default)
    python analytics_report.py --week          # Mon–Fri of current/most-recent week
    python analytics_report.py --all           # entire history
    python analytics_report.py --date 2026-05-07
"""
import argparse
import sqlite3
import sys
from collections import defaultdict, deque
from datetime import date, timedelta
from pathlib import Path
from db import DB_PATH, get_connection

SCRIPT_DIR = Path(__file__).resolve().parent

# Order in which to display rejection categories.
PRIORITY_CATEGORIES = [
    "market_hours",
    "stale_signal",
    "duplicate_webhook",
    "symbol_override",
    "circuit_breaker",
    "ghost_sell",
    "cooldown",
    "churn_window",
    "churn_price",
    "exposure_cap",
    "daily_symbol_buy_limit",
    "correlation_cap",
    "fundamental_score",
    "trend_gate",
    "trend_confirmation",
    "macro_risk",
    "macro_position_limit",
    "market_bias_avoid",
    "soft_avoid_prediction_gate",
    "live_bias_downgrade",
    "chase_prevention",
    "setup_policy",
    "addon_momentum_gate",
    "session_momentum_gate",
    "prediction_gate",
    "confidence_gate",
    "second_look",
    "cash_safe_symbol",
    "cash_safe_position_limit",
    "cash_safe_daily_symbol_limit",
    "cash_safe_confidence",
    "order_path_exception",
    "claude_rejection",
]
# Anything not in this set whose rejection_reason starts with "<word>:" gets
# bucketed under "claude_rejection" rather than being exploded as its own
# category. Keeps the breakdown readable when historical Claude reasons leak in.
KNOWN_CATEGORIES = set(PRIORITY_CATEGORIES) - {"claude_rejection"}


def _resolve_range(args):
    """Return (header, sql_clause, params).

    Clause is appended to existing WHERE blocks; it always starts with ' AND '
    (or is empty for --all)."""
    if args.all:
        return ("ALL TIME", "", ())
    if args.week:
        today = date.today()
        monday = today - timedelta(days=today.weekday())  # Mon=0..Sun=6
        friday = monday + timedelta(days=4)
        end_excl = friday + timedelta(days=1)
        header = f"WEEK {monday.isoformat()} → {friday.isoformat()}"
        return (
            header,
            " AND timestamp >= ? AND timestamp < ?",
            (monday.isoformat(), end_excl.isoformat()),
        )
    target = args.date or date.today().isoformat()
    return (f"DATE {target}", " AND timestamp LIKE ?", (f"{target}%",))


def _section(title):
    bar = "─" * max(0, 60 - len(title) - 4)
    print(f"\n── {title} {bar}")


def _render_execution(con, clause, params):
    _section("EXECUTION")
    sql = f"""
        SELECT
          SUM(CASE WHEN action='buy'  AND (rejection_reason IS NULL
                       OR rejection_reason NOT LIKE 'synthetic_bracket_exit:%')
                   THEN 1 ELSE 0 END) AS filled_buys,
          SUM(CASE WHEN action='sell' AND (rejection_reason IS NULL
                       OR rejection_reason NOT LIKE 'synthetic_bracket_exit:%')
                   THEN 1 ELSE 0 END) AS filled_sells,
          SUM(CASE WHEN rejection_reason LIKE 'synthetic_bracket_exit:%'
                   THEN 1 ELSE 0 END) AS synth_exits
        FROM trades
        WHERE approved = 1
          AND order_status IN ('filled', 'partially_filled')
          AND qty IS NOT NULL
          AND fill_price IS NOT NULL
          {clause}
    """
    row = con.execute(sql, params).fetchone()
    print(f"  Filled buys              : {row['filled_buys'] or 0}")
    print(f"  Filled sells             : {row['filled_sells'] or 0}")
    print(f"  Synthetic exits          : {row['synth_exits'] or 0}")

    # Open tracked positions (FIFO net qty across the entire DB, not date-filtered
    # because open-position state is current, not range-bound)
    open_rows = con.execute("""
        SELECT symbol,
            SUM(CASE WHEN action='buy' THEN COALESCE(qty,0)
                     ELSE -COALESCE(qty,0) END) AS net_qty
        FROM trades
        WHERE order_id IS NOT NULL
          AND order_status IN ('filled', 'partially_filled')
        GROUP BY symbol
        HAVING net_qty > 0
    """).fetchall()
    syms = ", ".join(r['symbol'] for r in open_rows) or "—"
    print(f"  Open tracked positions   : {len(open_rows)} ({syms})")

    # fill_events forensic table (may not exist on older DBs)
    try:
        fe = con.execute(
            f"SELECT COUNT(*) AS n FROM fill_events WHERE 1=1{clause}", params
        ).fetchone()
        print(f"  Fill events captured     : {fe['n']}")
    except sqlite3.OperationalError:
        print(f"  Fill events captured     : (fill_events table not present)")


def _render_filters(con, clause, params):
    _section("RISK FILTERS")
    rows = con.execute(f"""
        SELECT
          CASE
            WHEN instr(rejection_reason, ':') > 0
              THEN substr(rejection_reason, 1, instr(rejection_reason, ':') - 1)
            ELSE 'uncategorized'
          END AS category,
          COUNT(*) AS n
        FROM trades
        WHERE approved = 0
          AND rejection_reason IS NOT NULL
          {clause}
        GROUP BY category
        ORDER BY n DESC
    """, params).fetchall()
    counts = {}
    for r in rows:
        cat = r['category']
        if cat in KNOWN_CATEGORIES:
            counts[cat] = counts.get(cat, 0) + r['n']
        else:
            # Free-form rejection text from Claude (pre-Stage-5 history, or any
            # claude-level approved=false reason that lacks a known prefix)
            counts['claude_rejection'] = counts.get('claude_rejection', 0) + r['n']
    if not counts:
        print("  (no rejections in range)")
        return
    for cat in PRIORITY_CATEGORIES:
        n = counts.get(cat, 0)
        if n:
            print(f"  {cat:<26}: {n}")
    print(f"  {'TOTAL':<26}: {sum(counts.values())}")


def _fifo_match(con, clause, params):
    """FIFO-match buys to sells (per symbol). Time-respecting: a sell only
    matches against buys that came BEFORE it in chronological order.

    Algorithm matches trade_matcher.match_trades exactly so the two views
    agree on match counts and P&L. Includes synthetic_bracket_exit rows on
    the sell side (autonomous stop-loss / take-profit fills)."""
    rows = con.execute(f"""
        SELECT timestamp, symbol, action, qty, fill_price, signal_price
        FROM trades
        WHERE approved = 1
          AND action IN ('buy', 'sell')
          AND qty IS NOT NULL
          AND fill_price IS NOT NULL
          AND order_status IN ('filled', 'partially_filled')
          {clause}
        ORDER BY timestamp ASC, id ASC
    """, params).fetchall()

    open_lots = defaultdict(deque)
    matches = []
    for r in rows:
        symbol = r['symbol']
        action = r['action']
        qty = float(r['qty'] or 0)
        price = float(r['fill_price'] or 0)
        if not symbol or qty <= 0 or price <= 0:
            continue

        if action == 'buy':
            open_lots[symbol].append({'qty': qty, 'price': price, 'ts': r['timestamp']})
            continue

        remaining = qty
        while remaining > 0 and open_lots[symbol]:
            lot = open_lots[symbol][0]
            matched_qty = min(remaining, lot['qty'])
            pnl = (price - lot['price']) * matched_qty
            matches.append({
                'symbol': symbol, 'qty': matched_qty,
                'buy_price': lot['price'], 'sell_price': price,
                'pnl': pnl, 'buy_ts': lot['ts'], 'sell_ts': r['timestamp'],
            })
            lot['qty'] -= matched_qty
            remaining -= matched_qty
            if lot['qty'] <= 0:
                open_lots[symbol].popleft()
    return matches

def _render_session_momentum_attribution(con, clause, params):
    _section("SESSION MOMENTUM ATTRIBUTION")

    rows = con.execute(f"""
        SELECT
            COALESCE(session_trend_label, 'unknown') AS label,
            COUNT(*) AS total,
            SUM(CASE WHEN approved = 1 THEN 1 ELSE 0 END) AS approved,
            SUM(CASE WHEN approved = 0 THEN 1 ELSE 0 END) AS rejected
        FROM trades
        WHERE LOWER(action) = 'buy'
          {clause}
        GROUP BY COALESCE(session_trend_label, 'unknown')
        ORDER BY total DESC
    """, params).fetchall()

    if not rows:
        print("  (no buy signals in range)")
        return

    print(f"  {'Label':<22} {'Total':>6} {'Approved':>9} {'Rejected':>9} {'Approval%':>9}")
    print(f"  {'-'*22} {'-'*6} {'-'*9} {'-'*9} {'-'*9}")

    for r in rows:
        total = r["total"] or 0
        approved = r["approved"] or 0
        rejected = r["rejected"] or 0
        approval_rate = (approved / total * 100) if total else 0.0

        print(
            f"  {(r['label'] or 'unknown'):<22} "
            f"{total:>6} {approved:>9} {rejected:>9} {approval_rate:>8.1f}%"
        )

def _render_performance(matches):
    _section("PERFORMANCE")
    if not matches:
        print("  (no closed trades in range)")
        return
    total_pnl = sum(m['pnl'] for m in matches)
    wins   = [m for m in matches if m['pnl'] > 0]
    losses = [m for m in matches if m['pnl'] < 0]
    flats  = [m for m in matches if m['pnl'] == 0]
    n = len(matches)
    win_rate = (len(wins) / n * 100) if n else 0.0
    avg_win  = (sum(m['pnl'] for m in wins) / len(wins)) if wins else 0.0
    avg_loss = (sum(m['pnl'] for m in losses) / len(losses)) if losses else 0.0
    sum_wins = sum(m['pnl'] for m in wins)
    sum_losses_abs = abs(sum(m['pnl'] for m in losses))
    if sum_losses_abs > 0:
        profit_factor = f"{sum_wins / sum_losses_abs:.2f}"
    elif sum_wins > 0:
        profit_factor = "∞ (no losses)"
    else:
        profit_factor = "—"
    expectancy = total_pnl / n if n else 0.0

    print(f"  Realized P&L             : ${total_pnl:+.2f}")
    print(f"  Closed trades            : {n} ({len(wins)}W / {len(losses)}L / {len(flats)}F)")
    print(f"  Win rate                 : {win_rate:.1f}%")
    print(f"  Avg win                  : ${avg_win:+.2f}")
    print(f"  Avg loss                 : ${avg_loss:+.2f}")
    print(f"  Profit factor            : {profit_factor}")
    print(f"  Expectancy per trade     : ${expectancy:+.2f}")


def _render_per_symbol(matches):
    _section("PER-SYMBOL PERFORMANCE")
    if not matches:
        print("  (none)")
        return
    by_sym = defaultdict(lambda: {'pnl': 0.0, 'wins': 0, 'losses': 0, 'flat': 0, 'qty': 0})
    for m in matches:
        d = by_sym[m['symbol']]
        d['pnl'] += m['pnl']
        d['qty'] += m['qty']
        if m['pnl'] > 0:
            d['wins'] += 1
        elif m['pnl'] < 0:
            d['losses'] += 1
        else:
            d['flat'] += 1
    print(f"  {'Symbol':<7} {'P&L':>10}  {'Closed':>6}  {'W/L/F':>10}  {'Qty':>5}")
    print(f"  {'-'*7} {'-'*10}  {'-'*6}  {'-'*10}  {'-'*5}")
    for sym, d in sorted(by_sym.items(), key=lambda x: -x[1]['pnl']):
        wlf = f"{d['wins']}/{d['losses']}/{d['flat']}"
        closed = d['wins'] + d['losses'] + d['flat']
        print(f"  {sym:<7} ${d['pnl']:>+9.2f}  {closed:>6}  {wlf:>10}  {d['qty']:>5}")


def pct_gap(a, b):
    if not a and not b:
        return 0
    denom = max(abs(a), abs(b), 1)
    return abs(a - b) / denom * 100


def _render_data_quality(con, clause, params, matches):
    _section("DATA QUALITY")
    mclause = _matched_clause(clause)

    best_effort_trade_count = len(matches)
    best_effort_pnl = sum(m['pnl'] for m in matches)

    try:
        row = con.execute(f"""
            SELECT COUNT(*) AS n, COALESCE(SUM(realized_pnl), 0) AS pnl
            FROM matched_trades
            WHERE 1=1 {mclause}
        """, params).fetchone()
        confirmed_trade_count = row['n']
        confirmed_pnl = row['pnl']
    except sqlite3.OperationalError:
        print("  (matched_trades table not present — run trade_matcher.py first)")
        return

    pnl_gap = pct_gap(best_effort_pnl, confirmed_pnl)
    trade_gap = pct_gap(best_effort_trade_count, confirmed_trade_count)

    print(f"  Confirmed-fill trades    : {confirmed_trade_count}")
    print(f"  Best-effort FIFO trades  : {best_effort_trade_count}")
    print(f"  Confirmed P&L            : ${confirmed_pnl:+.2f}")
    print(f"  Best-effort P&L          : ${best_effort_pnl:+.2f}")
    print(f"  P&L gap                  : {pnl_gap:.1f}%")
    print(f"  Trade-count gap          : {trade_gap:.1f}%")

    if pnl_gap > 10 or trade_gap > 10:
        print()
        print("  WARNING: analytics views diverge materially because some historical rows")
        print("  lack fill_price. Use confirmed-fill analytics for attribution; use")
        print("  best-effort FIFO as a broad outcome sanity check.")

        bad_rows = con.execute(f"""
            SELECT id, timestamp, symbol, action, qty, signal_price, fill_price,
                   order_id, order_status
            FROM trades
            WHERE approved = 1
              AND action IN ('buy', 'sell')
              AND qty IS NOT NULL
              AND fill_price IS NULL
              {clause}
            ORDER BY timestamp
        """, params).fetchall()
        if bad_rows:
            print()
            print(f"  Rows missing fill_price ({len(bad_rows)} total):")
            print(f"    {'id':>4} {'timestamp':<19} {'sym':<5} {'side':<4} {'qty':>4} {'sig$':>8} {'order_id':<10} {'status':<14}")
            for r in bad_rows[:20]:
                oid = (r['order_id'] or '—')[:8]
                status = r['order_status'] or '—'
                sig = r['signal_price']
                sig_str = f"{sig:.2f}" if sig else '—'
                print(f"    {r['id']:>4} {r['timestamp']:<19} {r['symbol']:<5} {r['action']:<4} {r['qty']:>4} {sig_str:>8} {oid:<10} {status:<14}")
            if len(bad_rows) > 20:
                print(f"    ... ({len(bad_rows) - 20} more)")


def _matched_clause(clause):
    """Adapt the trades-table 'timestamp' date clause to matched_trades, which
    keys date filtering on exit_timestamp (the close event)."""
    return clause.replace("timestamp", "exit_timestamp")


def _render_matched_attribution(con, clause, params):
    _section("MATCHED-TRADE ATTRIBUTION")
    mclause = _matched_clause(clause)

    try:
        agg = con.execute(f"""
            SELECT
              COUNT(*) AS trades,
              COALESCE(SUM(realized_pnl), 0) AS pnl,
              COALESCE(AVG(realized_pnl), 0) AS expectancy,
              CASE WHEN COUNT(*) > 0 THEN
                SUM(CASE WHEN won = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*)
              ELSE 0 END AS win_rate
            FROM matched_trades
            WHERE 1=1 {mclause}
        """, params).fetchone()
    except sqlite3.OperationalError:
        print("  (matched_trades table not present — run trade_matcher.py first)")
        return

    if agg["trades"] == 0:
        print("  (no matched trades in range)")
        return

    pf_row = con.execute(f"""
        SELECT
          COALESCE(SUM(CASE WHEN realized_pnl > 0 THEN realized_pnl ELSE 0 END), 0) AS gross_profit,
          COALESCE(ABS(SUM(CASE WHEN realized_pnl < 0 THEN realized_pnl ELSE 0 END)), 0) AS gross_loss
        FROM matched_trades
        WHERE 1=1 {mclause}
    """, params).fetchone()
    gp = pf_row["gross_profit"]
    gl = pf_row["gross_loss"]
    if gl > 0:
        pf = f"{gp / gl:.2f}"
    elif gp > 0:
        pf = "∞ (no losses)"
    else:
        pf = "—"

    print(f"  Trades                   : {agg['trades']}")
    print(f"  Realized P&L             : ${agg['pnl']:+.2f}")
    print(f"  Expectancy               : ${agg['expectancy']:+.2f}")
    print(f"  Win rate                 : {agg['win_rate']:.1f}%")
    print(f"  Gross profit / loss      : ${gp:.2f} / ${gl:.2f}")
    print(f"  Profit factor            : {pf}")

    # Per-symbol from matched_trades
    sym_rows = con.execute(f"""
        SELECT symbol, COUNT(*) AS trades,
               SUM(realized_pnl) AS pnl, AVG(realized_pnl) AS expectancy,
               SUM(CASE WHEN won = 1 THEN 1 ELSE 0 END) * 100.0 / COUNT(*) AS win_rate
        FROM matched_trades
        WHERE 1=1 {mclause}
        GROUP BY symbol
        ORDER BY pnl DESC
    """, params).fetchall()
    if sym_rows:
        print()
        print(f"  Per-symbol (from matched_trades):")
        print(f"    {'Symbol':<7} {'Trades':>6}  {'P&L':>10}  {'Expect':>9}  {'Win%':>6}")
        print(f"    {'-'*7} {'-'*6}  {'-'*10}  {'-'*9}  {'-'*6}")
        for r in sym_rows:
            print(f"    {r['symbol']:<7} {r['trades']:>6}  ${r['pnl']:>+9.2f}  ${r['expectancy']:>+8.2f}  {r['win_rate']:>5.1f}%")

    # Context attribution placeholders — likely empty for trades that predate
    # the schema migration; populates as new post-migration matches accumulate.
    macro_rows = con.execute(f"""
        SELECT macro_regime, COUNT(*) AS n,
               SUM(realized_pnl) AS pnl, AVG(realized_pnl) AS expectancy
        FROM matched_trades
        WHERE macro_regime IS NOT NULL {mclause}
        GROUP BY macro_regime
        ORDER BY pnl DESC
    """, params).fetchall()
    print()
    print("  By macro_regime:")
    if not macro_rows:
        print("    (none — historical entries predate the context migration)")
    else:
        for r in macro_rows:
            print(f"    {r['macro_regime']:<22} n={r['n']:>3}  P&L=${r['pnl']:>+9.2f}  expect=${r['expectancy']:>+7.2f}")

    trend_rows = con.execute(f"""
        SELECT trend_direction, trend_strength, COUNT(*) AS n,
               SUM(realized_pnl) AS pnl, AVG(realized_pnl) AS expectancy
        FROM matched_trades
        WHERE trend_direction IS NOT NULL {mclause}
        GROUP BY trend_direction, trend_strength
        ORDER BY pnl DESC
    """, params).fetchall()
    print()
    print("  By trend (direction/strength):")
    if not trend_rows:
        print("    (none — historical entries predate the context migration)")
    else:
        for r in trend_rows:
            label = f"{r['trend_direction']}/{r['trend_strength']}"
            print(f"    {label:<22} n={r['n']:>3}  P&L=${r['pnl']:>+9.2f}  expect=${r['expectancy']:>+7.2f}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.strip().splitlines()[0])
    rng = parser.add_mutually_exclusive_group()
    rng.add_argument('--all',  action='store_true', help='Across the entire trades.db history')
    rng.add_argument('--week', action='store_true', help='Mon–Fri of current/most-recent week')
    rng.add_argument('--date', help='Single date YYYY-MM-DD (default = today)')
    args = parser.parse_args()

    if not DB_PATH.exists():
        print(f"ERROR: {DB_PATH} not found", file=sys.stderr)
        sys.exit(1)

    header, clause, params = _resolve_range(args)

    con = get_connection(DB_PATH)

    print(f"\n{'=' * 60}")
    print(f"  Trading Bot Analytics Report — {header}")
    print(f"{'=' * 60}")

    _render_execution(con, clause, params)
    _render_filters(con, clause, params)
    matches = _fifo_match(con, clause, params)
    _render_session_momentum_attribution(con, clause, params)
    _render_performance(matches)
    _render_per_symbol(matches)
    _render_matched_attribution(con, clause, params)
    _render_data_quality(con, clause, params, matches)

    print()
    con.close()


if __name__ == "__main__":
    main()
