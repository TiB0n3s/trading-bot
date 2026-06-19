#!/usr/bin/env python3
"""
Event attribution report — read-only.

Joins:
  daily_symbol_events
  daily_symbol_context
  trades
  matched_trades

Purpose:
  Evaluate whether structured news/product/fundamental events are associated
  with better or worse trading outcomes.

Usage:
  python3 event_attribution_report.py --date 2026-05-26
  python3 event_attribution_report.py --date 2026-05-26 --symbol AAPL
  python3 event_attribution_report.py --date 2026-05-26 --event-type product_launch
  python3 event_attribution_report.py --date 2026-05-26 --details
"""

import argparse
from collections import defaultdict
from datetime import date

from db import DB_PATH, get_connection
from market_intelligence.intelligence_store import init_intelligence_tables


def money(v):
    if v is None:
        return "-"
    sign = "+" if float(v) >= 0 else ""
    return f"{sign}${float(v):.2f}"


def pct(v):
    if v is None:
        return "-"
    sign = "+" if float(v) >= 0 else ""
    return f"{sign}{float(v):.2f}%"


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
    return (a / b) if b else 0.0


def load_events(con, target_date, symbol=None, event_type=None):
    params = [target_date]
    filters = ["market_date = ?"]

    if symbol:
        filters.append("symbol = ?")
        params.append(symbol.upper())

    if event_type:
        filters.append("event_type = ?")
        params.append(event_type)

    where = " AND ".join(filters)

    return con.execute(
        f"""
        SELECT *
        FROM daily_symbol_events
        WHERE {where}
        ORDER BY symbol, event_type, id
        """,
        params,
    ).fetchall()


def load_context_by_symbol(con, target_date):
    rows = con.execute(
        """
        SELECT *
        FROM daily_symbol_context
        WHERE market_date = ?
        """,
        (target_date,),
    ).fetchall()
    return {r["symbol"]: r for r in rows}


def trade_stats_for_symbol(con, target_date, symbol):
    """Return same-day trade stats for a symbol."""
    trades = con.execute(
        """
        SELECT *
        FROM trades
        WHERE timestamp LIKE ?
          AND symbol = ?
        ORDER BY timestamp ASC, id ASC
        """,
        (f"{target_date}%", symbol),
    ).fetchall()

    total_signals = len(trades)
    approved = sum(1 for r in trades if int(r["approved"] or 0) == 1)
    rejected = total_signals - approved
    orders = sum(1 for r in trades if r["order_id"])
    filled = sum(
        1 for r in trades
        if r["order_status"] in ("filled", "partially_filled")
        and r["fill_price"] is not None
    )

    buys = sum(1 for r in trades if (r["action"] or "").lower() == "buy")
    sells = sum(1 for r in trades if (r["action"] or "").lower() == "sell")

    return {
        "total_signals": total_signals,
        "approved": approved,
        "rejected": rejected,
        "approval_rate": safe_div(approved, total_signals) * 100,
        "orders": orders,
        "filled": filled,
        "buys": buys,
        "sells": sells,
    }


def pnl_stats_for_symbol(con, target_date, symbol):
    """Return matched-trade P&L stats for same-day exits."""
    try:
        rows = con.execute(
            """
            SELECT *
            FROM matched_trades
            WHERE exit_timestamp LIKE ?
              AND symbol = ?
            ORDER BY exit_timestamp ASC
            """,
            (f"{target_date}%", symbol),
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
    }


def aggregate_bucket(rows, key):
    buckets = defaultdict(lambda: {
        "event_count": 0,
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
        "catalyst_scores": [],
        "consumer_scores": [],
        "profit_scores": [],
        "supply_risks": [],
        "competitive_risks": [],
    })

    for r in rows:
        label = r.get(key) or "-"
        b = buckets[label]

        b["event_count"] += 1
        b["symbols"].add(r["symbol"])
        b["signals"] += r["total_signals"]
        b["approved"] += r["approved"]
        b["orders"] += r["orders"]
        b["filled"] += r["filled"]
        b["closed_trades"] += r["closed_trades"]
        b["wins"] += r["wins"]
        b["losses"] += r["losses"]
        b["flat"] += r["flat"]
        b["realized_pnl"] += r["realized_pnl"]

        for src, dest in (
            ("catalyst_score", "catalyst_scores"),
            ("consumer_appetite_score", "consumer_scores"),
            ("profit_potential_score", "profit_scores"),
            ("supply_chain_risk_score", "supply_risks"),
            ("competitive_risk_score", "competitive_risks"),
        ):
            if r.get(src) is not None:
                b[dest].append(float(r[src]))

    out = []
    for label, b in buckets.items():
        def avg(vals):
            return sum(vals) / len(vals) if vals else None

        out.append({
            "label": label,
            "event_count": b["event_count"],
            "symbol_count": len(b["symbols"]),
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
            "avg_catalyst_score": avg(b["catalyst_scores"]),
            "avg_consumer_score": avg(b["consumer_scores"]),
            "avg_profit_score": avg(b["profit_scores"]),
            "avg_supply_risk": avg(b["supply_risks"]),
            "avg_competitive_risk": avg(b["competitive_risks"]),
        })

    return sorted(out, key=lambda x: (x["realized_pnl"], x["event_count"]), reverse=True)


def print_bucket(title, rows):
    print()
    print(f"── {title} " + "─" * max(0, 92 - len(title)))

    if not rows:
        print("  No rows.")
        return

    headers = [
        "Bucket", "Ev", "Sym", "Sig", "Appr%", "Ord", "Fill", "Closed",
        "Win%", "P&L", "Cat", "Demand", "Profit", "SupRisk"
    ]
    widths = [24, 4, 4, 5, 7, 5, 5, 7, 6, 10, 6, 7, 7, 8]
    fmt = " ".join(f"{{:<{w}}}" for w in widths)

    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))

    for r in rows:
        print(fmt.format(
            short(r["label"], 24),
            r["event_count"],
            r["symbol_count"],
            r["signals"],
            num(r["approval_rate"], 1),
            r["orders"],
            r["filled"],
            r["closed_trades"],
            num(r["win_rate"], 1),
            money(r["realized_pnl"]),
            num(r["avg_catalyst_score"], 0),
            num(r["avg_consumer_score"], 0),
            num(r["avg_profit_score"], 0),
            num(r["avg_supply_risk"], 0),
        ))


def print_details(rows):
    print()
    print("── Event Details ─────────────────────────────────────────────────────────────")

    if not rows:
        print("  No details.")
        return

    headers = [
        "Sym", "Type", "Impact", "Relevance", "Signals", "Appr", "Orders",
        "Closed", "P&L", "Cat", "Demand", "Supply", "Summary"
    ]
    widths = [7, 18, 18, 22, 7, 5, 6, 7, 10, 5, 7, 7, 46]
    fmt = " ".join(f"{{:<{w}}}" for w in widths)

    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))

    for r in rows:
        print(fmt.format(
            r["symbol"],
            short(r["event_type"], 18),
            short(r["expected_market_impact"], 18),
            short(r["trade_relevance"], 22),
            r["total_signals"],
            r["approved"],
            r["orders"],
            r["closed_trades"],
            money(r["realized_pnl"]),
            num(r["catalyst_score"], 0),
            num(r["consumer_appetite_score"], 0),
            num(r["supply_chain_risk_score"], 0),
            short(r["event_summary"], 46),
        ))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--symbol")
    parser.add_argument("--event-type")
    parser.add_argument("--details", action="store_true")
    args = parser.parse_args()

    init_intelligence_tables()

    with get_connection(DB_PATH) as con:
        events = load_events(con, args.date, args.symbol, args.event_type)
        context_by_symbol = load_context_by_symbol(con, args.date)

        enriched = []
        for e in events:
            symbol = e["symbol"]
            ctx = context_by_symbol.get(symbol)

            trade_stats = trade_stats_for_symbol(con, args.date, symbol)
            pnl_stats = pnl_stats_for_symbol(con, args.date, symbol)

            enriched.append({
                "event_id": e["id"],
                "market_date": e["market_date"],
                "symbol": symbol,
                "event_type": e["event_type"],
                "event_subtype": e["event_subtype"],
                "event_summary": e["event_summary"],
                "source": e["source"],
                "expected_market_impact": e["expected_market_impact"],
                "trade_relevance": e["trade_relevance"],
                "time_horizon": e["time_horizon"],
                "confidence": e["confidence"],

                "consumer_appetite_score": e["consumer_appetite_score"],
                "revenue_impact_score": e["revenue_impact_score"],
                "profit_potential_score": e["profit_potential_score"],
                "margin_risk_score": e["margin_risk_score"],
                "supply_chain_risk_score": e["supply_chain_risk_score"],
                "materials_risk_score": e["materials_risk_score"],
                "regulatory_risk_score": e["regulatory_risk_score"],
                "competitive_risk_score": e["competitive_risk_score"],
                "execution_risk_score": e["execution_risk_score"],
                "macro_risk_score": e["macro_risk_score"],

                "context_bias": ctx["bias"] if ctx else None,
                "context_entry_quality": ctx["entry_quality"] if ctx else None,
                "catalyst_score": ctx["catalyst_score"] if ctx else None,

                **trade_stats,
                **pnl_stats,
            })

    print("=" * 132)
    print(f"  Event Attribution Report — {args.date}")
    print("=" * 132)
    if args.symbol:
        print(f"  symbol filter     : {args.symbol.upper()}")
    if args.event_type:
        print(f"  event_type filter : {args.event_type}")
    print(f"  events found      : {len(enriched)}")
    print(f"  symbols           : {len(set(r['symbol'] for r in enriched))}")
    print()

    if not enriched:
        print("No events found for this filter.")
        return 1

    total_events = len(enriched)
    total_signals = sum(r["total_signals"] for r in enriched)
    total_orders = sum(r["orders"] for r in enriched)
    total_filled = sum(r["filled"] for r in enriched)
    total_closed = sum(r["closed_trades"] for r in enriched)
    total_pnl = sum(r["realized_pnl"] for r in enriched)
    total_wins = sum(r["wins"] for r in enriched)

    print("Summary")
    print("-------")
    print(f"  Events             : {total_events}")
    print(f"  Signals            : {total_signals}")
    print(f"  Orders             : {total_orders}")
    print(f"  Filled orders      : {total_filled}")
    print(f"  Closed trades      : {total_closed}")
    print(f"  Win rate           : {safe_div(total_wins, total_closed) * 100:.1f}%")
    print(f"  Realized P&L       : {money(total_pnl)}")

    print_bucket("By Event Type", aggregate_bucket(enriched, "event_type"))
    print_bucket("By Market Impact", aggregate_bucket(enriched, "expected_market_impact"))
    print_bucket("By Trade Relevance", aggregate_bucket(enriched, "trade_relevance"))

    if args.details:
        print_details(enriched)

    print()
    print("Notes")
    print("-----")
    print("  This is attribution, not causation.")
    print("  P&L uses matched_trades exits on the same date as the event.")
    print("  If no trades occurred after an event, it still appears as an event with zero signals/orders.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
