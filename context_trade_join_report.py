#!/usr/bin/env python3
"""
Context trade join report — read-only.

Purpose:
  Evaluate whether daily_symbol_context fields are associated with better or
  worse trade outcomes.

Joins:
  daily_symbol_context by market_date + symbol
  trades by timestamp date + symbol
  matched_trades by exit_timestamp date + symbol

Usage:
  python3 context_trade_join_report.py --date 2026-05-26
  python3 context_trade_join_report.py --date 2026-05-26 --symbol AAPL
  python3 context_trade_join_report.py --date 2026-05-26 --details
  python3 context_trade_join_report.py --week
  python3 context_trade_join_report.py --all
"""

import argparse
from collections import defaultdict
from datetime import date, timedelta

from db import DB_PATH, get_connection
from market_intelligence.intelligence_store import init_intelligence_tables


def money(v):
    if v is None:
        return "-"
    sign = "+" if float(v) >= 0 else ""
    return f"{sign}${float(v):.2f}"


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


def bucket_score(value, label="score"):
    if value is None:
        return f"{label}:missing"
    try:
        v = float(value)
    except (TypeError, ValueError):
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


def bucket_pct(value, label="pct"):
    if value is None:
        return f"{label}:missing"
    try:
        v = float(value)
    except (TypeError, ValueError):
        return f"{label}:invalid"

    if v >= 2:
        return f"{label}:+2%+"
    if v >= 0.5:
        return f"{label}:+0.5_to_2%"
    if v > -0.5:
        return f"{label}:-0.5_to_+0.5%"
    if v > -2:
        return f"{label}:-2_to_-0.5%"
    return f"{label}:-2%-"


def resolve_range(args):
    if args.all:
        return "ALL", None, None

    if args.week:
        today = date.today()
        monday = today - timedelta(days=today.weekday())
        saturday = monday + timedelta(days=5)
        return f"WEEK {monday.isoformat()} to {(saturday - timedelta(days=1)).isoformat()}", monday.isoformat(), saturday.isoformat()

    target = args.date or date.today().isoformat()
    next_day = (date.fromisoformat(target) + timedelta(days=1)).isoformat()
    return f"DATE {target}", target, next_day


def load_context_rows(con, start_date, end_date, symbol=None):
    params = []
    where = ["1=1"]

    if start_date:
        where.append("market_date >= ?")
        params.append(start_date)
    if end_date:
        where.append("market_date < ?")
        params.append(end_date)
    if symbol:
        where.append("symbol = ?")
        params.append(symbol.upper())

    rows = con.execute(
        f"""
        SELECT *
        FROM daily_symbol_context
        WHERE {' AND '.join(where)}
        ORDER BY market_date, symbol
        """,
        params,
    ).fetchall()

    return rows


def trade_stats(con, market_date, symbol):
    rows = con.execute(
        """
        SELECT *
        FROM trades
        WHERE timestamp LIKE ?
          AND symbol = ?
        ORDER BY timestamp ASC, id ASC
        """,
        (f"{market_date}%", symbol),
    ).fetchall()

    total = len(rows)
    approved = sum(1 for r in rows if int(r["approved"] or 0) == 1)
    rejected = total - approved
    orders = sum(1 for r in rows if r["order_id"])
    filled = sum(
        1 for r in rows
        if r["order_status"] in ("filled", "partially_filled")
        and r["fill_price"] is not None
    )

    buy_signals = sum(1 for r in rows if (r["action"] or "").lower() == "buy")
    sell_signals = sum(1 for r in rows if (r["action"] or "").lower() == "sell")

    return {
        "signals": total,
        "approved": approved,
        "rejected": rejected,
        "approval_rate": safe_div(approved, total) * 100,
        "orders": orders,
        "filled": filled,
        "buy_signals": buy_signals,
        "sell_signals": sell_signals,
    }


def pnl_stats(con, market_date, symbol):
    try:
        rows = con.execute(
            """
            SELECT *
            FROM matched_trades
            WHERE exit_timestamp LIKE ?
              AND symbol = ?
            ORDER BY exit_timestamp ASC
            """,
            (f"{market_date}%", symbol),
        ).fetchall()
    except Exception:
        rows = []

    total_pnl = sum(float(r["realized_pnl"] or 0) for r in rows)
    wins = sum(1 for r in rows if float(r["realized_pnl"] or 0) > 0)
    losses = sum(1 for r in rows if float(r["realized_pnl"] or 0) < 0)
    flat = sum(1 for r in rows if float(r["realized_pnl"] or 0) == 0)

    return {
        "closed_trades": len(rows),
        "realized_pnl": total_pnl,
        "wins": wins,
        "losses": losses,
        "flat": flat,
        "win_rate": safe_div(wins, len(rows)) * 100,
        "expectancy": safe_div(total_pnl, len(rows)),
    }


def enrich_context_rows(con, context_rows):
    enriched = []

    for ctx in context_rows:
        market_date = ctx["market_date"]
        symbol = ctx["symbol"]

        ts = trade_stats(con, market_date, symbol)
        ps = pnl_stats(con, market_date, symbol)

        enriched.append({
            "market_date": market_date,
            "symbol": symbol,

            "source": ctx["source"],
            "macro_sentiment": ctx["macro_sentiment"],
            "macro_regime": ctx["macro_regime"],
            "risk_multiplier": ctx["risk_multiplier"],
            "bias": ctx["bias"],
            "confidence": ctx["confidence"],
            "fundamental_score": ctx["fundamental_score"],
            "risk_level": ctx["risk_level"],
            "entry_quality": ctx["entry_quality"],
            "avoid_type": ctx["avoid_type"],

            "daily_pct": ctx["daily_pct"],
            "intraday_pct": ctx["intraday_pct"],
            "momentum_30m_pct": ctx["momentum_30m_pct"],
            "catalyst_score": ctx["catalyst_score"],
            "relative_strength_score": ctx["relative_strength_score"],
            "sector_alignment": ctx["sector_alignment"],
            "index_alignment": ctx["index_alignment"],
            "liquidity_quality": ctx["liquidity_quality"],
            "volume_context": ctx["volume_context"],
            "price_location": ctx["price_location"],

            "consumer_appetite_score": ctx["consumer_appetite_score"],
            "profit_potential_score": ctx["profit_potential_score"],
            "supply_chain_risk_score": ctx["supply_chain_risk_score"],
            "materials_risk_score": ctx["materials_risk_score"],
            "competitive_risk_score": ctx["competitive_risk_score"],
            "execution_risk_score": ctx["execution_risk_score"],

            "reason": ctx["reason"],

            **ts,
            **ps,
        })

    return enriched


def aggregate(rows, key_func):
    buckets = defaultdict(lambda: {
        "context_rows": 0,
        "active_symbols": set(),
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
        "rs_scores": [],
        "daily_pcts": [],
        "intra_pcts": [],
        "consumer_scores": [],
        "profit_scores": [],
        "supply_risks": [],
    })

    for r in rows:
        label = key_func(r) or "-"
        b = buckets[label]

        b["context_rows"] += 1
        if r["signals"] > 0:
            b["active_symbols"].add(r["symbol"])

        b["signals"] += r["signals"]
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
            ("relative_strength_score", "rs_scores"),
            ("daily_pct", "daily_pcts"),
            ("intraday_pct", "intra_pcts"),
            ("consumer_appetite_score", "consumer_scores"),
            ("profit_potential_score", "profit_scores"),
            ("supply_chain_risk_score", "supply_risks"),
        ):
            if r.get(src) is not None:
                b[dest].append(float(r[src]))

    out = []
    for label, b in buckets.items():
        def avg(vals):
            return sum(vals) / len(vals) if vals else None

        out.append({
            "label": label,
            "context_rows": b["context_rows"],
            "active_symbols": len(b["active_symbols"]),
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
            "avg_catalyst_score": avg(b["catalyst_scores"]),
            "avg_rs_score": avg(b["rs_scores"]),
            "avg_daily_pct": avg(b["daily_pcts"]),
            "avg_intraday_pct": avg(b["intra_pcts"]),
            "avg_consumer_score": avg(b["consumer_scores"]),
            "avg_profit_score": avg(b["profit_scores"]),
            "avg_supply_risk": avg(b["supply_risks"]),
        })

    return sorted(out, key=lambda r: (r["realized_pnl"], r["signals"]), reverse=True)


def print_bucket(title, rows, limit=None):
    print()
    print(f"── {title} " + "─" * max(0, 100 - len(title)))

    if not rows:
        print("  No rows.")
        return

    if limit:
        rows = rows[:limit]

    headers = [
        "Bucket", "Ctx", "Act", "Sig", "Appr%", "Ord", "Fill",
        "Closed", "Win%", "P&L", "Exp", "Cat", "RS", "Daily%"
    ]
    widths = [26, 5, 5, 5, 7, 5, 5, 7, 6, 10, 8, 6, 6, 8]
    fmt = " ".join(f"{{:<{w}}}" for w in widths)

    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))

    for r in rows:
        print(fmt.format(
            short(r["label"], 26),
            r["context_rows"],
            r["active_symbols"],
            r["signals"],
            num(r["approval_rate"], 1),
            r["orders"],
            r["filled"],
            r["closed_trades"],
            num(r["win_rate"], 1),
            money(r["realized_pnl"]),
            money(r["expectancy"]),
            num(r["avg_catalyst_score"], 0),
            num(r["avg_rs_score"], 0),
            num(r["avg_daily_pct"], 2),
        ))


def print_details(rows, only_active=False):
    print()
    print("── Details ─────────────────────────────────────────────────────────────────")

    if only_active:
        rows = [r for r in rows if r["signals"] > 0 or r["closed_trades"] > 0]

    if not rows:
        print("  No detail rows.")
        return

    headers = [
        "Date", "Sym", "Bias", "Risk", "Entry", "Cat", "RS", "Daily%",
        "Intra%", "Sig", "Ord", "Closed", "P&L", "Reason"
    ]
    widths = [11, 7, 8, 10, 18, 5, 5, 8, 8, 4, 4, 6, 10, 42]
    fmt = " ".join(f"{{:<{w}}}" for w in widths)

    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))

    for r in rows:
        print(fmt.format(
            r["market_date"],
            r["symbol"],
            short(r["bias"], 8),
            short(r["risk_level"], 10),
            short(r["entry_quality"], 18),
            num(r["catalyst_score"], 0),
            num(r["relative_strength_score"], 0),
            num(r["daily_pct"], 2),
            num(r["intraday_pct"], 2),
            r["signals"],
            r["orders"],
            r["closed_trades"],
            money(r["realized_pnl"]),
            short(r["reason"], 42),
        ))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--date")
    parser.add_argument("--week", action="store_true")
    parser.add_argument("--all", action="store_true")
    parser.add_argument("--symbol")
    parser.add_argument("--details", action="store_true")
    parser.add_argument("--active-only", action="store_true", help="Detail rows only for symbols with signals/trades")
    parser.add_argument("--limit", type=int, help="Limit bucket rows per section")
    args = parser.parse_args()

    init_intelligence_tables()

    label, start_date, end_date = resolve_range(args)

    with get_connection(DB_PATH) as con:
        context_rows = load_context_rows(con, start_date, end_date, args.symbol)
        enriched = enrich_context_rows(con, context_rows)

    print("=" * 132)
    print(f"  Context Trade Join Report — {label}")
    print("=" * 132)
    if args.symbol:
        print(f"  symbol filter : {args.symbol.upper()}")
    print(f"  context rows  : {len(enriched)}")
    print(f"  active rows   : {sum(1 for r in enriched if r['signals'] > 0 or r['closed_trades'] > 0)}")
    print()

    if not enriched:
        print("No daily_symbol_context rows found.")
        return 1

    total_signals = sum(r["signals"] for r in enriched)
    total_orders = sum(r["orders"] for r in enriched)
    total_filled = sum(r["filled"] for r in enriched)
    total_closed = sum(r["closed_trades"] for r in enriched)
    total_pnl = sum(r["realized_pnl"] for r in enriched)
    total_wins = sum(r["wins"] for r in enriched)

    print("Summary")
    print("-------")
    print(f"  Signals       : {total_signals}")
    print(f"  Orders        : {total_orders}")
    print(f"  Filled        : {total_filled}")
    print(f"  Closed trades : {total_closed}")
    print(f"  Win rate      : {safe_div(total_wins, total_closed) * 100:.1f}%")
    print(f"  Realized P&L  : {money(total_pnl)}")
    print(f"  Expectancy    : {money(safe_div(total_pnl, total_closed))}")

    print_bucket("By Macro Regime", aggregate(enriched, lambda r: r["macro_regime"]), args.limit)
    print_bucket("By Bias", aggregate(enriched, lambda r: r["bias"]), args.limit)
    print_bucket("By Risk Level", aggregate(enriched, lambda r: r["risk_level"]), args.limit)
    print_bucket("By Entry Quality", aggregate(enriched, lambda r: r["entry_quality"]), args.limit)
    print_bucket("By Avoid Type", aggregate(enriched, lambda r: r["avoid_type"]), args.limit)
    print_bucket("By Sector Alignment", aggregate(enriched, lambda r: r["sector_alignment"]), args.limit)
    print_bucket("By Index Alignment", aggregate(enriched, lambda r: r["index_alignment"]), args.limit)
    print_bucket("By Price Location", aggregate(enriched, lambda r: r["price_location"]), args.limit)
    print_bucket("By Volume Context", aggregate(enriched, lambda r: r["volume_context"]), args.limit)
    print_bucket("By Catalyst Score", aggregate(enriched, lambda r: bucket_score(r["catalyst_score"], "cat")), args.limit)
    print_bucket("By Relative Strength Score", aggregate(enriched, lambda r: bucket_score(r["relative_strength_score"], "rs")), args.limit)
    print_bucket("By Daily % Bucket", aggregate(enriched, lambda r: bucket_pct(r["daily_pct"], "daily")), args.limit)
    print_bucket("By Intraday % Bucket", aggregate(enriched, lambda r: bucket_pct(r["intraday_pct"], "intra")), args.limit)
    print_bucket("By Supply Chain Risk", aggregate(enriched, lambda r: bucket_score(r["supply_chain_risk_score"], "supply")), args.limit)

    if args.details:
        print_details(enriched, only_active=args.active_only)

    print()
    print("Notes")
    print("-----")
    print("  This report is attribution, not causation.")
    print("  Context rows are one row per symbol per market date.")
    print("  Trade stats join by same date + symbol.")
    print("  P&L uses matched_trades exits on the same date.")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
