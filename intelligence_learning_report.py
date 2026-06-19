#!/usr/bin/env python3
"""
Intelligence learning report — read-only.

Purpose:
  Analyze whether collected intelligence events and context fields are associated
  with better or worse trading outcomes.

This is the bridge between:
  - daily_symbol_events
  - daily_symbol_context
  - trades
  - matched_trades

Usage:
  python3 intelligence_learning_report.py --date 2026-05-26
  python3 intelligence_learning_report.py --all
  python3 intelligence_learning_report.py --symbol AAPL
"""

import argparse
from collections import defaultdict
from datetime import date, timedelta

from db import DB_PATH, get_connection
from market_intelligence.intelligence_store import init_intelligence_tables


def money(v):
    sign = "+" if float(v or 0) >= 0 else ""
    return f"{sign}${float(v or 0):.2f}"


def num(v, digits=1):
    if v is None:
        return "-"
    return f"{float(v):.{digits}f}"


def short(v, width):
    if v is None:
        return "-"
    s = str(v)
    return s if len(s) <= width else s[: width - 1] + "…"


def safe_div(a, b):
    return a / b if b else 0.0


def bucket(value, label):
    if value is None:
        return f"{label}:missing"
    try:
        v = float(value)
    except Exception:
        return f"{label}:invalid"

    if v >= 80:
        return f"{label}:80-100"
    if v >= 60:
        return f"{label}:60-79"
    if v >= 40:
        return f"{label}:40-59"
    if v >= 20:
        return f"{label}:20-39"
    return f"{label}:0-19"


def resolve_range(args):
    if args.all:
        return "ALL", None, None

    target = args.date or date.today().isoformat()
    next_day = (date.fromisoformat(target) + timedelta(days=1)).isoformat()
    return f"DATE {target}", target, next_day


def load_event_context_rows(con, start_date, end_date, symbol=None):
    params = []
    where = ["1=1"]

    if start_date:
        where.append("e.market_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("e.market_date < ?")
        params.append(end_date)
    if symbol:
        where.append("e.symbol = ?")
        params.append(symbol.upper())

    sql = f"""
        SELECT
            e.id AS event_id,
            e.market_date,
            e.symbol,
            e.event_type,
            e.expected_market_impact,
            e.trade_relevance,
            e.time_horizon,
            e.confidence AS event_confidence,
            e.consumer_appetite_score,
            e.revenue_impact_score,
            e.profit_potential_score,
            e.margin_risk_score,
            e.supply_chain_risk_score,
            e.materials_risk_score,
            e.regulatory_risk_score,
            e.competitive_risk_score,
            e.execution_risk_score,
            e.macro_risk_score,
            e.event_summary,

            c.bias,
            c.confidence AS context_confidence,
            c.risk_level,
            c.entry_quality,
            c.avoid_type,
            c.catalyst_score,
            c.relative_strength_score,
            c.daily_pct,
            c.intraday_pct,
            c.momentum_30m_pct,
            c.sector_alignment,
            c.index_alignment
        FROM daily_symbol_events e
        LEFT JOIN daily_symbol_context c
          ON c.market_date = e.market_date
         AND c.symbol = e.symbol
        WHERE {' AND '.join(where)}
        ORDER BY e.market_date, e.symbol, e.id
    """

    return con.execute(sql, params).fetchall()


def trade_stats(con, market_date, symbol):
    rows = con.execute(
        """
        SELECT *
        FROM trades
        WHERE timestamp LIKE ?
          AND symbol = ?
        """,
        (f"{market_date}%", symbol),
    ).fetchall()

    signals = len(rows)
    approved = sum(1 for r in rows if int(r["approved"] or 0) == 1)
    orders = sum(1 for r in rows if r["order_id"])
    filled = sum(
        1 for r in rows
        if r["order_status"] in ("filled", "partially_filled")
        and r["fill_price"] is not None
    )

    return {
        "signals": signals,
        "approved": approved,
        "approval_rate": safe_div(approved, signals) * 100,
        "orders": orders,
        "filled": filled,
    }


def pnl_stats(con, market_date, symbol):
    try:
        rows = con.execute(
            """
            SELECT *
            FROM matched_trades
            WHERE exit_timestamp LIKE ?
              AND symbol = ?
            """,
            (f"{market_date}%", symbol),
        ).fetchall()
    except Exception:
        rows = []

    pnl = sum(float(r["realized_pnl"] or 0) for r in rows)
    wins = sum(1 for r in rows if float(r["realized_pnl"] or 0) > 0)
    losses = sum(1 for r in rows if float(r["realized_pnl"] or 0) < 0)
    flat = sum(1 for r in rows if float(r["realized_pnl"] or 0) == 0)

    return {
        "closed_trades": len(rows),
        "realized_pnl": pnl,
        "wins": wins,
        "losses": losses,
        "flat": flat,
        "win_rate": safe_div(wins, len(rows)) * 100,
        "expectancy": safe_div(pnl, len(rows)),
    }


def enrich_rows(con, rows):
    enriched = []

    for r in rows:
        ts = trade_stats(con, r["market_date"], r["symbol"])
        ps = pnl_stats(con, r["market_date"], r["symbol"])

        item = dict(r)
        item.update(ts)
        item.update(ps)
        enriched.append(item)

    return enriched


def aggregate(rows, key_fn):
    buckets = defaultdict(lambda: {
        "events": 0,
        "symbols": set(),
        "signals": 0,
        "approved": 0,
        "orders": 0,
        "filled": 0,
        "closed_trades": 0,
        "wins": 0,
        "losses": 0,
        "flat": 0,
        "realized_pnl": 0.0,
        "expectancy_items": [],
    })

    for r in rows:
        label = key_fn(r) or "-"
        b = buckets[label]

        b["events"] += 1
        b["symbols"].add(r["symbol"])
        b["signals"] += r["signals"]
        b["approved"] += r["approved"]
        b["orders"] += r["orders"]
        b["filled"] += r["filled"]
        b["closed_trades"] += r["closed_trades"]
        b["wins"] += r["wins"]
        b["losses"] += r["losses"]
        b["flat"] += r["flat"]
        b["realized_pnl"] += r["realized_pnl"]

        if r["closed_trades"]:
            b["expectancy_items"].append(r["expectancy"])

    out = []

    for label, b in buckets.items():
        out.append({
            "label": label,
            "events": b["events"],
            "symbols": len(b["symbols"]),
            "signals": b["signals"],
            "approved": b["approved"],
            "approval_rate": safe_div(b["approved"], b["signals"]) * 100,
            "orders": b["orders"],
            "filled": b["filled"],
            "closed_trades": b["closed_trades"],
            "wins": b["wins"],
            "losses": b["losses"],
            "flat": b["flat"],
            "win_rate": safe_div(b["wins"], b["closed_trades"]) * 100,
            "realized_pnl": b["realized_pnl"],
            "expectancy": safe_div(b["realized_pnl"], b["closed_trades"]),
        })

    return sorted(out, key=lambda x: (x["expectancy"], x["realized_pnl"], x["events"]), reverse=True)


def print_bucket(title, rows, limit=None):
    print()
    print(f"── {title} " + "─" * max(0, 96 - len(title)))

    if not rows:
        print("  No rows.")
        return

    if limit:
        rows = rows[:limit]

    headers = [
        "Bucket", "Ev", "Sym", "Sig", "Appr%", "Ord", "Fill",
        "Closed", "Win%", "P&L", "Exp"
    ]
    widths = [34, 5, 5, 5, 7, 5, 5, 7, 6, 10, 10]
    fmt = " ".join(f"{{:<{w}}}" for w in widths)

    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))

    for r in rows:
        print(fmt.format(
            short(r["label"], 34),
            r["events"],
            r["symbols"],
            r["signals"],
            num(r["approval_rate"], 1),
            r["orders"],
            r["filled"],
            r["closed_trades"],
            num(r["win_rate"], 1),
            money(r["realized_pnl"]),
            money(r["expectancy"]),
        ))


def print_top_insights(rows):
    print()
    print("── Early Learning Signals ─────────────────────────────────────────────")

    if not rows:
        print("  No event rows available.")
        return

    closed = [r for r in rows if r["closed_trades"] > 0]
    if not closed:
        print("  No closed trades tied to event/context rows yet.")
        print("  The learner will become useful after several sessions with events and matched trades.")
        return

    best = sorted(closed, key=lambda r: r["expectancy"], reverse=True)[:5]
    worst = sorted(closed, key=lambda r: r["expectancy"])[:5]

    print()
    print("  Best event/context rows by expectancy:")
    for r in best:
        print(
            f"    {r['market_date']} {r['symbol']} "
            f"{r['event_type']} / {r['expected_market_impact']} / {r['trade_relevance']} "
            f"Exp={money(r['expectancy'])} P&L={money(r['realized_pnl'])} "
            f"closed={r['closed_trades']}"
        )

    print()
    print("  Worst event/context rows by expectancy:")
    for r in worst:
        print(
            f"    {r['market_date']} {r['symbol']} "
            f"{r['event_type']} / {r['expected_market_impact']} / {r['trade_relevance']} "
            f"Exp={money(r['expectancy'])} P&L={money(r['realized_pnl'])} "
            f"closed={r['closed_trades']}"
        )


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--symbol")
    parser.add_argument("--limit", type=int, default=12)
    args = parser.parse_args()

    init_intelligence_tables()
    label, start_date, end_date = resolve_range(args)

    with get_connection(DB_PATH) as con:
        rows = load_event_context_rows(con, start_date, end_date, args.symbol)
        enriched = enrich_rows(con, rows)

    print("=" * 132)
    print(f"  Intelligence Learning Report — {label}")
    print("=" * 132)
    if args.symbol:
        print(f"  symbol filter : {args.symbol.upper()}")
    print(f"  event rows    : {len(enriched)}")
    print(f"  symbols       : {len(set(r['symbol'] for r in enriched))}")

    total_signals = sum(r["signals"] for r in enriched)
    total_orders = sum(r["orders"] for r in enriched)
    total_closed = sum(r["closed_trades"] for r in enriched)
    total_pnl = sum(r["realized_pnl"] for r in enriched)
    total_wins = sum(r["wins"] for r in enriched)

    print()
    print("Summary")
    print("-------")
    print(f"  Signals       : {total_signals}")
    print(f"  Orders        : {total_orders}")
    print(f"  Closed trades : {total_closed}")
    print(f"  Win rate      : {safe_div(total_wins, total_closed) * 100:.1f}%")
    print(f"  Realized P&L  : {money(total_pnl)}")
    print(f"  Expectancy    : {money(safe_div(total_pnl, total_closed))}")

    print_bucket("Learned by Event Type", aggregate(enriched, lambda r: r["event_type"]), args.limit)
    print_bucket("Learned by Expected Market Impact", aggregate(enriched, lambda r: r["expected_market_impact"]), args.limit)
    print_bucket("Learned by Trade Relevance", aggregate(enriched, lambda r: r["trade_relevance"]), args.limit)
    print_bucket("Learned by Bias", aggregate(enriched, lambda r: r["bias"]), args.limit)
    print_bucket("Learned by Entry Quality", aggregate(enriched, lambda r: r["entry_quality"]), args.limit)
    print_bucket("Learned by Risk Level", aggregate(enriched, lambda r: r["risk_level"]), args.limit)
    print_bucket("Learned by Catalyst Score", aggregate(enriched, lambda r: bucket(r["catalyst_score"], "cat")), args.limit)
    print_bucket("Learned by Consumer Appetite", aggregate(enriched, lambda r: bucket(r["consumer_appetite_score"], "demand")), args.limit)
    print_bucket("Learned by Profit Potential", aggregate(enriched, lambda r: bucket(r["profit_potential_score"], "profit")), args.limit)
    print_bucket("Learned by Supply Chain Risk", aggregate(enriched, lambda r: bucket(r["supply_chain_risk_score"], "supply")), args.limit)
    print_bucket("Learned by Competitive Risk", aggregate(enriched, lambda r: bucket(r["competitive_risk_score"], "comp")), args.limit)

    print_top_insights(enriched)

    print()
    print("Notes")
    print("-----")
    print("  This is still attribution, not causation.")
    print("  Use several sessions of data before changing live trading rules.")
    print("  Next step after enough data: persist these learning summaries and feed them into morning context.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
