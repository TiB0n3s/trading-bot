#!/usr/bin/env python3
"""
Observe-only prediction report.

Reads feature_snapshots + labeled_setups and summarizes forward outcomes.

Usage:
  python3 prediction_report.py
  python3 prediction_report.py --limit 10
  python3 prediction_report.py --symbol QQQ
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, timedelta
from statistics import mean
from typing import Sequence

from db import DB_PATH, get_connection


def pct(v: float | None) -> str:
    if v is None:
        return "-"
    sign = "+" if v >= 0 else ""
    return f"{sign}{v:.3f}%"


def short(v, width: int) -> str:
    if v is None:
        return "-"
    s = str(v)
    return s if len(s) <= width else s[: width - 1] + "…"

def sample_flag(count: int, warn_below: int = 5) -> str:
    return "*" if count < warn_below else ""

def print_section(title: str) -> None:
    print()
    print("── " + title + " " + "─" * max(0, 72 - len(title)))


def avg(values: Sequence[float]) -> float | None:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    return round(mean(vals), 6)


def win_rate(values: Sequence[float], threshold: float = 0.0) -> float | None:
    vals = [float(v) for v in values if v is not None]
    if not vals:
        return None
    wins = sum(1 for v in vals if v > threshold)
    return round((wins / len(vals)) * 100.0, 2)


def bucket_relative_strength(v: float | None) -> str:
    if v is None:
        return "unknown"
    if v <= -0.30:
        return "weak"
    if v >= 0.30:
        return "strong"
    return "neutral"

def bucket_vwap_distance(v: float | None) -> str:
    if v is None:
        return "unknown"
    if v <= -0.75:
        return "far_below_vwap"
    if v <= -0.15:
        return "below_vwap"
    if v < 0.15:
        return "near_vwap"
    if v < 0.75:
        return "above_vwap"
    return "far_above_vwap"

def load_rows(
    symbol: str | None = None,
    horizon: str = "15m",
    session: str | None = None,
    target_date: str | None = None,
    last_n_days: int | None = None,
):
    clauses = []
    params: list = []

    horizon_col = {
        "5m": "ls.ret_fwd_5m",
        "15m": "ls.ret_fwd_15m",
        "30m": "ls.ret_fwd_30m",
    }[horizon]
    clauses.append(f"{horizon_col} IS NOT NULL")

    if symbol:
        clauses.append("fs.symbol = ?")
        params.append(symbol.upper())

    if session:
        clauses.append("fs.market_session = ?")
        params.append(session)

    if target_date:
        clauses.append("fs.timestamp LIKE ?")
        params.append(f"{target_date}%")
    elif last_n_days is not None:
        start_date = (date.today() - timedelta(days=last_n_days - 1)).isoformat()
        clauses.append("substr(fs.timestamp, 1, 10) >= ?")
        params.append(start_date)

    where_sql = " AND ".join(clauses)

    with get_connection(DB_PATH) as con:
        rows = con.execute(
            f"""
            SELECT
                fs.id AS snapshot_id,
                fs.timestamp,
                fs.symbol,
                fs.market_session,
                fs.market_bias,
                fs.trend_direction,
                fs.trend_strength,
                fs.relative_strength_5m,
                fs.distance_from_vwap,
                fs.ret_5m,
                fs.ret_15m,
                fs.bar_timeframe,
                fs.bar_count,
                fs.setup_label,
                fs.setup_recommendation,
                fs.setup_score,
                fs.setup_confidence,
                fs.setup_key,
                ls.ret_fwd_5m,
                ls.ret_fwd_15m,
                ls.ret_fwd_30m,
                ls.max_up_15m,
                ls.max_down_15m,
                ls.outcome_label
            FROM feature_snapshots fs
            JOIN labeled_setups ls
              ON ls.snapshot_id = fs.id
            WHERE {where_sql}
            ORDER BY fs.timestamp ASC
            """,
            params,
        ).fetchall()

    return rows

def load_trade_rows(
    symbol: str | None = None,
    session: str | None = None,
    target_date: str | None = None,
    last_n_days: int | None = None,
):
    clauses = []
    params: list = []

    if symbol:
        clauses.append("symbol = ?")
        params.append(symbol.upper())

    if target_date:
        clauses.append("timestamp LIKE ?")
        params.append(f"{target_date}%")
    elif last_n_days is not None:
        start_date = (date.today() - timedelta(days=last_n_days - 1)).isoformat()
        clauses.append("substr(timestamp, 1, 10) >= ?")
        params.append(start_date)

    if session:
        clauses.append("1 = 1")

    where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""

    with get_connection(DB_PATH) as con:
        rows = con.execute(
            f"""
            SELECT
                id,
                timestamp,
                symbol,
                action,
                approved,
                rejection_reason,
                confidence,
                market_bias,
                trend_direction,
                trend_strength,
                setup_label,
                setup_policy_action,
                setup_policy_reason
            FROM trades
            {where_sql}
            ORDER BY timestamp ASC
            """,
            params,
        ).fetchall()

    return rows

def summarize_rows(rows) -> dict:
    ret5 = [r["ret_fwd_5m"] for r in rows if r["ret_fwd_5m"] is not None]
    ret15 = [r["ret_fwd_15m"] for r in rows if r["ret_fwd_15m"] is not None]
    ret30 = [r["ret_fwd_30m"] for r in rows if r["ret_fwd_30m"] is not None]
    max_up = [r["max_up_15m"] for r in rows if r["max_up_15m"] is not None]
    max_down = [r["max_down_15m"] for r in rows if r["max_down_15m"] is not None]

    return {
        "count": len(rows),
        "avg_ret_5m": avg(ret5),
        "avg_ret_15m": avg(ret15),
        "avg_ret_30m": avg(ret30),
        "win_rate_5m": win_rate(ret5),
        "win_rate_15m": win_rate(ret15),
        "win_rate_30m": win_rate(ret30),
        "avg_max_up_15m": avg(max_up),
        "avg_max_down_15m": avg(max_down),
    }


def grouped_summary(rows, key_fn, min_samples: int = 1, horizon: str = "15m"):
    groups = defaultdict(list)
    for row in rows:
        groups[key_fn(row)].append(row)

    horizon_avg_key = {
        "5m": "avg_ret_5m",
        "15m": "avg_ret_15m",
        "30m": "avg_ret_30m",
    }[horizon]

    out = []
    for key, group_rows in groups.items():
        if len(group_rows) < min_samples:
            continue
        summary = summarize_rows(group_rows)
        summary["group"] = key
        out.append(summary)

    out.sort(
        key=lambda x: (
            x[horizon_avg_key] is not None,
            x[horizon_avg_key] if x[horizon_avg_key] is not None else -999,
            x["count"],
        ),
        reverse=True,
    )
    return out

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
            x["approval_rate"] is not None,
            x["approval_rate"] if x["approval_rate"] is not None else -999,
            x["count"],
        ),
        reverse=True,
    )
    return out

def print_leaderboard(
    title: str,
    rows: list[dict],
    limit: int,
    horizon: str,
    reverse: bool = True,
) -> None:
    print_section(title)

    if not rows:
        print("No rows.")
        return

    horizon_avg_key = {
        "5m": "avg_ret_5m",
        "15m": "avg_ret_15m",
        "30m": "avg_ret_30m",
    }[horizon]
    horizon_win_key = {
        "5m": "win_rate_5m",
        "15m": "win_rate_15m",
        "30m": "win_rate_30m",
    }[horizon]
    horizon_label = horizon.upper()

    filtered = [r for r in rows if r.get(horizon_avg_key) is not None]

    if reverse:
        filtered = [r for r in filtered if r[horizon_avg_key] > 0]
    else:
        filtered = [r for r in filtered if r[horizon_avg_key] < 0]

    if not filtered:
        print("No qualifying rows.")
        return

    ranked = sorted(
        filtered,
        key=lambda r: (r.get(horizon_avg_key), r.get("count", 0)),
        reverse=reverse,
    )

    headers = [
        "Group",
        "Count",
        f"Avg{horizon_label}",
        f"Win{horizon_label}",
        "Avg30",
        "MaxUp15",
        "MaxDn15",
    ]
    widths = [54, 7, 10, 8, 10, 10, 10]
    fmt = " ".join(f"{{:<{w}}}" for w in widths)

    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))

    for row in ranked[:limit]:
        count = row.get("count", 0)
        group_label = f"{row.get('group')} {sample_flag(count)}".rstrip()

        print(
            fmt.format(
                short(group_label, 54),
                count,
                pct(row.get(horizon_avg_key)),
                f"{row[horizon_win_key]:.1f}%" if row.get(horizon_win_key) is not None else "-",
                pct(row.get("avg_ret_30m")),
                pct(row.get("avg_max_up_15m")),
                pct(row.get("avg_max_down_15m")),
            )
        )

    print()
    print("* low sample size (<5)")

def print_trade_table(title: str, rows: list[dict], limit: int) -> None:
    print_section(title)

    if not rows:
        print("No rows.")
        return

    headers = [
        "Group",
        "Count",
        "Approved",
        "Rejected",
        "Approval%",
    ]
    widths = [54, 7, 9, 9, 10]
    fmt = " ".join(f"{{:<{w}}}" for w in widths)

    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))

    for row in rows[:limit]:
        count = row.get("count", 0)
        group_label = f"{row.get('group')} {sample_flag(count)}".rstrip()

        print(
            fmt.format(
                short(group_label, 54),
                count,
                row.get("approved_count", 0),
                row.get("rejected_count", 0),
                f"{row['approval_rate']:.1f}%" if row.get("approval_rate") is not None else "-",
            )
        )

    print()
    print("* low sample size (<5)")

def print_table(title: str, rows: list[dict], limit: int, horizon: str) -> None:
    print_section(title)

    if not rows:
        print("No rows.")
        return

    horizon_avg_key = {
        "5m": "avg_ret_5m",
        "15m": "avg_ret_15m",
        "30m": "avg_ret_30m",
    }[horizon]
    horizon_win_key = {
        "5m": "win_rate_5m",
        "15m": "win_rate_15m",
        "30m": "win_rate_30m",
    }[horizon]
    horizon_label = horizon.upper()

    headers = [
        "Group",
        "Count",
        f"Avg{horizon_label}",
        f"Win{horizon_label}",
        "Avg30",
        "MaxUp15",
        "MaxDn15",
    ]
    widths = [54, 7, 10, 8, 10, 10, 10]
    fmt = " ".join(f"{{:<{w}}}" for w in widths)

    print(fmt.format(*headers))
    print(fmt.format(*["-" * w for w in widths]))

    for row in rows[:limit]:
        count = row.get("count", 0)
        group_label = f"{row.get('group')} {sample_flag(count)}".rstrip()

        print(
            fmt.format(
                short(group_label, 30),
                count,
                pct(row.get(horizon_avg_key)),
                f"{row[horizon_win_key]:.1f}%" if row.get(horizon_win_key) is not None else "-",
                pct(row.get("avg_ret_30m")),
                pct(row.get("avg_max_up_15m")),
                pct(row.get("avg_max_down_15m")),
            )
        )

    print()
    print("* low sample size (<5)")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--limit", type=int, default=10, help="Rows per section")
    parser.add_argument("--symbol", help="Filter to one symbol")
    parser.add_argument(
        "--horizon",
        choices=["5m", "15m", "30m"],
        default="15m",
        help="Forward-return horizon to require for report rows",
    )
    parser.add_argument(
        "--session",
        choices=["pre-market", "open", "after-hours", "closed"],
        help="Filter to one market session",
    )
    parser.add_argument(
        "--min-samples",
        type=int,
        default=1,
        help="Hide groups with fewer than this many samples",
    )
    parser.add_argument("--date", help="Filter to one date: YYYY-MM-DD")
    parser.add_argument("--today", action="store_true", help="Filter to today")
    parser.add_argument("--last-n-days", type=int, help="Filter to the last N calendar days")
    args = parser.parse_args()

    date_filters_used = sum(
        1 for x in (args.date, args.today, args.last_n_days is not None) if x
    )
    if date_filters_used > 1:
        parser.error("Use only one of --date, --today, or --last-n-days")

    target_date = None
    if args.today:
        target_date = date.today().isoformat()
    elif args.date:
        target_date = args.date

    trade_rows = load_trade_rows(
        symbol=args.symbol,
        session=args.session,
        target_date=target_date,
        last_n_days=args.last_n_days,
    )

    buy_trade_rows = [r for r in trade_rows if (r["action"] or "").lower() == "buy"]

    rows = load_rows(
        symbol=args.symbol,
        horizon=args.horizon,
        session=args.session,
        target_date=target_date,
        last_n_days=args.last_n_days,
    )

    if not rows:
        print(f"No labeled rows with ret_fwd_{args.horizon} found for the current filters.")
        return 0

    overall = summarize_rows(rows)

    live_overall = summarize_trade_rows(trade_rows)

    live_buy_overall = summarize_trade_rows(buy_trade_rows)

    print("=" * 96)
    print("  Prediction Report — observe-only")
    print("=" * 96)
    print(f"DB path            : {DB_PATH}")
    print(f"Symbol filter      : {args.symbol.upper() if args.symbol else 'ALL'}")
    print(f"Session filter     : {args.session if args.session else 'ALL'}")
    if target_date:
        print(f"Date filter        : {target_date}")
    elif args.last_n_days is not None:
        print(f"Date filter        : last {args.last_n_days} day(s)")
    else:
        print("Date filter        : ALL")
    print(f"Required horizon   : {args.horizon}")
    print(f"Min group samples  : {args.min_samples}")
    print(f"Labeled samples    : {overall['count']}")
    print(f"Live trade rows    : {live_overall['count']}")
    print(f"Live approvals     : {live_overall['approved_count']}")
    print(f"Live rejections    : {live_overall['rejected_count']}")
    print(
        f"Live approval rate : {live_overall['approval_rate']:.1f}%"
        if live_overall["approval_rate"] is not None
        else "Live approval rate : -"
    )
    print(f"Live BUY rows      : {live_buy_overall['count']}")
    print(f"Live BUY approvals : {live_buy_overall['approved_count']}")
    print(f"Live BUY rejects   : {live_buy_overall['rejected_count']}")
    print(
        f"Live BUY appr rate : {live_buy_overall['approval_rate']:.1f}%"
        if live_buy_overall["approval_rate"] is not None
        else "Live BUY appr rate : -"
    )
    print(f"Avg ret 5m         : {pct(overall['avg_ret_5m'])}")
    print(f"Avg ret 15m        : {pct(overall['avg_ret_15m'])}")
    print(f"Avg ret 30m        : {pct(overall['avg_ret_30m'])}")
    print(f"Win rate 5m        : {overall['win_rate_5m']:.1f}%" if overall["win_rate_5m"] is not None else "Win rate 5m        : -")
    print(f"Win rate 15m       : {overall['win_rate_15m']:.1f}%" if overall["win_rate_15m"] is not None else "Win rate 15m       : -")
    print(f"Win rate 30m       : {overall['win_rate_30m']:.1f}%" if overall["win_rate_30m"] is not None else "Win rate 30m       : -")
    print(f"Avg max up 15m     : {pct(overall['avg_max_up_15m'])}")
    print(f"Avg max down 15m   : {pct(overall['avg_max_down_15m'])}")

    by_symbol = grouped_summary(
        rows,
        lambda r: r["symbol"] or "unknown",
        min_samples=args.min_samples,
        horizon=args.horizon,
    )
    by_bias = grouped_summary(
        rows,
        lambda r: r["market_bias"] or "unknown",
        min_samples=args.min_samples,
        horizon=args.horizon,
    )
    by_trend_vwap = grouped_summary(
        rows,
        lambda r: (
            f"{r['trend_direction']}/{r['trend_strength']}|"
            f"{bucket_vwap_distance(r['distance_from_vwap'])}"
        )
        if r["trend_direction"] or r["trend_strength"]
        else f"unknown|{bucket_vwap_distance(r['distance_from_vwap'])}",
        min_samples=args.min_samples,
        horizon=args.horizon,
    )
    by_trend_vwap_rs = grouped_summary(
        rows,
        lambda r: (
            f"{r['trend_direction']}/{r['trend_strength']}|"
            f"{bucket_vwap_distance(r['distance_from_vwap'])}|"
            f"{bucket_relative_strength(r['relative_strength_5m'])}"
        )
        if r["trend_direction"] or r["trend_strength"]
        else (
            f"unknown|"
            f"{bucket_vwap_distance(r['distance_from_vwap'])}|"
            f"{bucket_relative_strength(r['relative_strength_5m'])}"
        ),
        min_samples=args.min_samples,
        horizon=args.horizon,
    )
    by_setup_label = grouped_summary(
        rows,
        lambda r: r["setup_label"] or "unknown",
        min_samples=args.min_samples,
        horizon=args.horizon,
    )
    by_setup_label = grouped_summary(
        rows,
        lambda r: (
            r["setup_label"]
            if "setup_label" in r.keys() and r["setup_label"]
            else "unknown"
        ),
        min_samples=args.min_samples,
        horizon=args.horizon,
    )
    trades_by_setup_label = grouped_trade_summary(
        trade_rows,
        lambda r: r["setup_label"] or "unknown",
        min_samples=args.min_samples,
    )
    trades_by_setup_policy = grouped_trade_summary(
        trade_rows,
        lambda r: r["setup_policy_action"] or "unknown",
        min_samples=args.min_samples,
    )
    trades_by_rejection_category = grouped_trade_summary(
        trade_rows,
        lambda r: (
            (r["rejection_reason"] or "approved").split(":", 1)[0]
            if int(r["approved"] or 0) == 0
            else "approved"
        ),
        min_samples=args.min_samples,
    )
    buy_trades_by_setup_label = grouped_trade_summary(
        buy_trade_rows,
        lambda r: r["setup_label"] or "unknown",
        min_samples=args.min_samples,
    )
    buy_trades_by_setup_policy = grouped_trade_summary(
        buy_trade_rows,
        lambda r: r["setup_policy_action"] or "unknown",
        min_samples=args.min_samples,
    )
    buy_trades_by_rejection_category = grouped_trade_summary(
        buy_trade_rows,
        lambda r: (
            (r["rejection_reason"] or "approved").split(":", 1)[0]
            if int(r["approved"] or 0) == 0
            else "approved"
        ),
        min_samples=args.min_samples,
    )
    setup_policy_block_rows = [
        r for r in buy_trade_rows
        if (r["rejection_reason"] or "").startswith("setup_policy:")
    ]

    buy_blocks_by_setup_label = grouped_trade_summary(
        setup_policy_block_rows,
        lambda r: r["setup_label"] or "unknown",
        min_samples=1,
    )

    buy_blocks_by_policy_reason = grouped_trade_summary(
        setup_policy_block_rows,
        lambda r: r["setup_policy_reason"] or "unknown",
        min_samples=1,
    )
    by_trend = grouped_summary(
        rows,
        lambda r: f"{r['trend_direction']}/{r['trend_strength']}"
        if r["trend_direction"] or r["trend_strength"]
        else "unknown",
        min_samples=args.min_samples,
        horizon=args.horizon,
    )
    by_rs = grouped_summary(
        rows,
        lambda r: bucket_relative_strength(r["relative_strength_5m"]),
        min_samples=args.min_samples,
        horizon=args.horizon,
    )
    by_vwap = grouped_summary(
        rows,
        lambda r: bucket_vwap_distance(r["distance_from_vwap"]),
        min_samples=args.min_samples,
        horizon=args.horizon,
    )
    by_bias_vwap = grouped_summary(
        rows,
        lambda r: f"{(r['market_bias'] or 'unknown')}|{bucket_vwap_distance(r['distance_from_vwap'])}",
        min_samples=args.min_samples,
        horizon=args.horizon,
    )


    print_table("By Symbol", by_symbol, args.limit, args.horizon)
    print_table("By Market Bias", by_bias, args.limit, args.horizon)
    print_table("By Trend", by_trend, args.limit, args.horizon)
    print_table("By Relative Strength Bucket", by_rs, args.limit, args.horizon)
    print_table("By VWAP Distance Bucket", by_vwap, args.limit, args.horizon)
    print_table("By Market Bias + VWAP", by_bias_vwap, args.limit, args.horizon)
    print_table("By Trend + VWAP", by_trend_vwap, args.limit, args.horizon)
    print_table("By Trend + VWAP + RS", by_trend_vwap_rs, args.limit, args.horizon)
    print_table("By Setup Label", by_setup_label, args.limit, args.horizon)
    print_trade_table("Live Trades by Setup Label", trades_by_setup_label, args.limit)
    print_trade_table("Live Trades by Setup Policy Action", trades_by_setup_policy, args.limit)
    print_trade_table("Live Trades by Rejection Category", trades_by_rejection_category, args.limit)
    print_trade_table("Live BUYs by Setup Label", buy_trades_by_setup_label, args.limit)
    print_trade_table("Live BUYs by Setup Policy Action", buy_trades_by_setup_policy, args.limit)
    print_trade_table("Live BUYs by Rejection Category", buy_trades_by_rejection_category, args.limit)
    print_trade_table("Setup Policy Blocks by Setup Label", buy_blocks_by_setup_label, args.limit)
    print_trade_table("Setup Policy Blocks by Policy Reason", buy_blocks_by_policy_reason, args.limit)
    print_leaderboard(
        "Top Combined Setups (Trend + VWAP + RS)",
        by_trend_vwap_rs,
        args.limit,
        args.horizon,
        reverse=True,
    )
    print_leaderboard(
        "Bottom Combined Setups (Trend + VWAP + RS)",
        by_trend_vwap_rs,
        args.limit,
        args.horizon,
        reverse=False,
    )
    print_leaderboard(
        "Top Setup Labels",
        by_setup_label,
        args.limit,
        args.horizon,
        reverse=True,
    )
    print_leaderboard(
        "Bottom Setup Labels",
        by_setup_label,
        args.limit,
        args.horizon,
        reverse=False,
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())