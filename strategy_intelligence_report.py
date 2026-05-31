#!/usr/bin/env python3
"""
Strategy Intelligence Report — schema-safe read-only report.

Usage:
  python3 strategy_intelligence_report.py
  python3 strategy_intelligence_report.py 2026-05-22
"""

import sys
from datetime import date
from collections import defaultdict
from repositories.strategy_intelligence_report_repo import (
    StrategyIntelligenceReportRepository,
)

repo = StrategyIntelligenceReportRepository()


def pct(n, d):
    return (n / d * 100.0) if d else 0.0


def short(text, n=80):
    text = str(text or "")
    return text if len(text) <= n else text[: n - 3] + "..."


def section(title):
    print()
    print("── " + title + " " + "─" * max(0, 76 - len(title)))


def get(row, key, default=None):
    try:
        return row[key]
    except Exception:
        return default


def parsed_buy_score(row):
    score = get(row, "buy_opportunity_score")
    if score is not None:
        try:
            return float(score)
        except Exception:
            pass

    reason = str(get(row, "rejection_reason") or "")
    marker = "buy_score="
    if marker not in reason:
        return None

    try:
        tail = reason.split(marker, 1)[1]
        raw = tail.split(";", 1)[0].strip()
        if raw in ("", "None", "none", "null"):
            return None
        return float(raw)
    except Exception:
        return None


def parsed_buy_rec(row):
    rec = get(row, "buy_opportunity_recommendation")
    if rec:
        return rec

    reason = str(get(row, "rejection_reason") or "")
    marker = "buy_rec="
    if marker not in reason:
        return None

    try:
        tail = reason.split(marker, 1)[1]
        raw = tail.split(";", 1)[0].strip()
        if raw in ("", "None", "none", "null"):
            return None
        return raw
    except Exception:
        return None


def parse_weakest_holding(row):
    reason = str(get(row, "rejection_reason") or "")
    marker = "weakest_holding="
    if marker not in reason:
        return None
    try:
        tail = reason.split(marker, 1)[1]
        raw = tail.split(" ", 1)[0].strip().strip(";")
        if raw in ("", "unknown", "None", "none", "null"):
            return None
        return raw
    except Exception:
        return None


def parse_weakest_plpc(row):
    reason = str(get(row, "rejection_reason") or "")
    marker = "plpc="
    if marker not in reason:
        return None
    try:
        tail = reason.split(marker, 1)[1]
        raw = tail.split("%", 1)[0].split(";", 1)[0].strip()
        return float(raw)
    except Exception:
        return None


def latest_sell_pressure_by_symbol(pos_rows):
    latest = {}
    for r in pos_rows:
        sym = get(r, "symbol")
        score = get(r, "sell_pressure_score")
        if not sym or score is None:
            continue
        latest[sym] = {
            "score": float(score),
            "rec": get(r, "sell_pressure_recommendation"),
            "action": get(r, "action"),
            "severity": get(r, "severity"),
            "unrealized_plpc": get(r, "unrealized_plpc"),
            "timestamp": get(r, "timestamp"),
        }
    return latest


def replacement_edge_label(edge):
    if edge is None:
        return "unknown"
    if edge >= 24:
        return "strong_replace_watch"
    if edge >= 18:
        return "replacement_watch"
    return "no_replace"


def fetch_buy_rows(repo, target_date):
    wanted = [
        "timestamp", "symbol", "action", "approved", "rejection_reason",
        "buy_opportunity_score", "buy_opportunity_recommendation",
        "buy_opportunity_reason",
        "market_bias", "risk_level", "entry_quality",
        "trend_direction", "trend_strength",
        "setup_label", "setup_policy_action",
        "prediction_score", "prediction_decision",
        "signal_price", "fill_price",
    ]
    return repo.select_existing(
        "trades",
        wanted,
        "WHERE timestamp LIKE ? AND LOWER(action) = 'buy' ORDER BY timestamp ASC",
        (f"{target_date}%",),
    )


def fetch_sell_rows(repo, target_date):
    wanted = [
        "timestamp", "symbol", "action", "approved", "rejection_reason",
        "fill_price", "signal_price",
        "realized_pnl", "realized_pl", "profit_loss", "pnl",
        "setup_label", "market_bias", "risk_level", "entry_quality",
    ]
    return repo.select_existing(
        "trades",
        wanted,
        "WHERE timestamp LIKE ? AND LOWER(action) = 'sell' ORDER BY timestamp ASC",
        (f"{target_date}%",),
    )


def fetch_position_momentum_rows(repo, target_date):
    wanted = [
        "timestamp", "symbol", "action", "severity", "reason",
        "trend_label", "trend_score",
        "session_return_pct", "momentum_5m_pct", "momentum_15m_pct",
        "momentum_30m_pct", "distance_from_vwap_pct",
        "unrealized_pl", "unrealized_plpc",
        "auto_sell_enabled", "order_submitted", "order_id",
        "sell_pressure_score", "sell_pressure_recommendation",
        "sell_pressure_reason",
    ]
    return repo.select_existing(
        "position_momentum_checks",
        wanted,
        "WHERE timestamp LIKE ? ORDER BY timestamp ASC",
        (f"{target_date}%",),
    )


def summarize_buy_opportunity(rows):
    section("BUY opportunity scoring")

    total = len(rows)
    approved = sum(1 for r in rows if get(r, "approved"))
    scored = [r for r in rows if get(r, "buy_opportunity_score") is not None]

    print(f"  BUY rows            : {total}")
    print(f"  Approved BUY rows   : {approved} ({pct(approved, total):.1f}%)")
    print(f"  Scored BUY rows     : {len(scored)} ({pct(len(scored), total):.1f}%)")

    if not scored:
        print("  No scored BUY rows yet.")
        return

    buckets = defaultdict(lambda: {"rows": 0, "approved": 0, "score_sum": 0.0})

    for r in scored:
        rec = get(r, "buy_opportunity_recommendation") or "unknown"
        buckets[rec]["rows"] += 1
        buckets[rec]["approved"] += int(get(r, "approved") or 0)
        buckets[rec]["score_sum"] += float(get(r, "buy_opportunity_score") or 0)

    print()
    print(f"  {'Recommendation':<24} {'Rows':>5} {'Approved':>8} {'Appr%':>8} {'AvgScore':>9}")
    print(f"  {'-'*24} {'-'*5} {'-'*8} {'-'*8} {'-'*9}")

    for rec, item in sorted(buckets.items(), key=lambda x: (-x[1]["rows"], x[0])):
        n = item["rows"]
        a = item["approved"]
        avg = item["score_sum"] / n if n else 0
        print(f"  {rec:<24} {n:>5} {a:>8} {pct(a, n):>7.1f}% {avg:>9.2f}")


def summarize_setup_labels(rows):
    section("Setup label outcomes")

    by_setup = defaultdict(lambda: {"rows": 0, "approved": 0, "scored": 0, "score_sum": 0.0})

    for r in rows:
        setup = get(r, "setup_label") or "-"
        by_setup[setup]["rows"] += 1
        by_setup[setup]["approved"] += int(get(r, "approved") or 0)

        if get(r, "buy_opportunity_score") is not None:
            by_setup[setup]["scored"] += 1
            by_setup[setup]["score_sum"] += float(get(r, "buy_opportunity_score") or 0)

    if not by_setup:
        print("  No setup rows.")
        return

    print(f"  {'Setup':<36} {'Rows':>5} {'Approved':>8} {'Appr%':>8} {'AvgBuyScore':>11}")
    print(f"  {'-'*36} {'-'*5} {'-'*8} {'-'*8} {'-'*11}")

    for setup, item in sorted(by_setup.items(), key=lambda x: (-x[1]["rows"], x[0]))[:25]:
        avg = item["score_sum"] / item["scored"] if item["scored"] else None
        avg_txt = f"{avg:.2f}" if avg is not None else "-"
        print(
            f"  {short(setup, 36):<36} {item['rows']:>5} {item['approved']:>8} "
            f"{pct(item['approved'], item['rows']):>7.1f}% {avg_txt:>11}"
        )


def summarize_rejections(rows):
    section("Rejection intelligence")

    rejected = [r for r in rows if not get(r, "approved")]
    by_bucket = defaultdict(int)

    for r in rejected:
        reason = get(r, "rejection_reason") or "unknown"
        bucket = reason.split(":", 1)[0]
        by_bucket[bucket] += 1

    if not by_bucket:
        print("  No BUY rejections.")
        return

    print(f"  {'Bucket':<34} {'Count':>7}")
    print(f"  {'-'*34} {'-'*7}")

    for bucket, count in sorted(by_bucket.items(), key=lambda x: -x[1])[:20]:
        print(f"  {bucket:<34} {count:>7}")


def summarize_replacement_intelligence(rows, pos_rows):
    section("Replacement intelligence / macro position limit")

    macro_rows = [
        r for r in rows
        if not get(r, "approved")
        and str(get(r, "rejection_reason") or "").startswith("macro_position_limit:")
    ]

    print(f"  Macro-position-limit rejects : {len(macro_rows)}")

    if not macro_rows:
        print("  No macro position limit rejects.")
        return

    scored = [r for r in macro_rows if parsed_buy_score(r) is not None]
    print(f"  Scored macro-limit rejects   : {len(scored)}")

    pressure_lookup = latest_sell_pressure_by_symbol(pos_rows)

    by_symbol = defaultdict(lambda: {"rows": 0, "scored": 0, "score_sum": 0.0, "max_score": None})
    by_rec = defaultdict(int)
    strong_candidates = []

    for r in macro_rows:
        sym = get(r, "symbol") or "-"
        by_symbol[sym]["rows"] += 1

        score = parsed_buy_score(r)
        rec = parsed_buy_rec(r) or "unscored"
        by_rec[rec] += 1

        if score is not None:
            score = float(score)
            by_symbol[sym]["scored"] += 1
            by_symbol[sym]["score_sum"] += score
            if by_symbol[sym]["max_score"] is None or score > by_symbol[sym]["max_score"]:
                by_symbol[sym]["max_score"] = score

            if rec in ("strong_buy_candidate", "small_buy_candidate") or score >= 7:
                strong_candidates.append(r)

    print()
    print("  Macro-limit rejects by recommendation:")
    for rec, count in sorted(by_rec.items(), key=lambda x: -x[1]):
        print(f"    {rec:<24} {count:>5}")

    print()
    print(f"  {'Symbol':<8} {'Rows':>5} {'Scored':>7} {'AvgScore':>9} {'MaxScore':>9}")
    print(f"  {'-'*8} {'-'*5} {'-'*7} {'-'*9} {'-'*9}")

    for sym, item in sorted(by_symbol.items(), key=lambda x: (-x[1]["rows"], x[0]))[:20]:
        avg = item["score_sum"] / item["scored"] if item["scored"] else None
        avg_txt = f"{avg:.2f}" if avg is not None else "-"
        max_txt = f"{item['max_score']:.2f}" if item["max_score"] is not None else "-"
        print(f"  {sym:<8} {item['rows']:>5} {item['scored']:>7} {avg_txt:>9} {max_txt:>9}")

    print()
    print("  Strong replacement candidates blocked by macro limit:")
    if not strong_candidates:
        print("    None yet.")
        return

    enriched = []
    for r in strong_candidates:
        candidate_score = parsed_buy_score(r)
        weakest = parse_weakest_holding(r)
        weakest_plpc = parse_weakest_plpc(r)
        weakest_pressure = pressure_lookup.get(weakest or "", {})
        weakest_pressure_score = weakest_pressure.get("score")

        edge = None
        if candidate_score is not None and weakest_pressure_score is not None:
            edge = float(candidate_score) + float(weakest_pressure_score)

        enriched.append((edge if edge is not None else -999, r, weakest, weakest_plpc, weakest_pressure))

    enriched = sorted(enriched, key=lambda x: x[0], reverse=True)[:20]

    print(
        f"    {'Time':<19} {'Cand':<6} {'BScore':>6} {'BRec':<22} "
        f"{'Weak':<6} {'WPress':>7} {'WPL%':>7} {'Edge':>7} {'Class':<22} {'Setup':<28}"
    )
    print(
        f"    {'-'*19} {'-'*6} {'-'*6} {'-'*22} "
        f"{'-'*6} {'-'*7} {'-'*7} {'-'*7} {'-'*22} {'-'*28}"
    )

    for _, r, weakest, weakest_plpc, weakest_pressure in enriched:
        candidate_score = parsed_buy_score(r)
        rec = parsed_buy_rec(r)
        weakest_pressure_score = weakest_pressure.get("score")

        edge = None
        if candidate_score is not None and weakest_pressure_score is not None:
            edge = float(candidate_score) + float(weakest_pressure_score)

        edge_txt = f"{edge:.1f}" if edge is not None else "-"
        wpress_txt = f"{weakest_pressure_score:.1f}" if weakest_pressure_score is not None else "-"
        wpl_txt = f"{weakest_plpc:.2f}" if weakest_plpc is not None else "-"
        label = replacement_edge_label(edge)

        print(
            f"    {get(r, 'timestamp'):<19} "
            f"{get(r, 'symbol'):<6} "
            f"{float(candidate_score or 0):>6.1f} "
            f"{str(rec or '-'):<22} "
            f"{str(weakest or '-'):<6} "
            f"{wpress_txt:>7} "
            f"{wpl_txt:>7} "
            f"{edge_txt:>7} "
            f"{label:<22} "
            f"{short(get(r, 'setup_label') or '-', 28):<28}"
        )


def summarize_position_momentum(rows):
    section("Position momentum / sell pressure")

    total = len(rows)
    if total == 0:
        print("  No position momentum rows.")
        return

    by_action = defaultdict(int)
    by_severity = defaultdict(int)
    pressure_buckets = defaultdict(int)
    scored = 0
    submitted = 0

    for r in rows:
        by_action[get(r, "action") or "-"] += 1
        by_severity[get(r, "severity") or "-"] += 1
        submitted += int(get(r, "order_submitted") or 0)

        rec = get(r, "sell_pressure_recommendation")
        if rec:
            pressure_buckets[rec] += 1
            scored += 1

    print(f"  Position checks       : {total}")
    print(f"  Sell-pressure scored  : {scored}")
    print(f"  Orders submitted      : {submitted}")

    print()
    print("  Actions:")
    for k, v in sorted(by_action.items(), key=lambda x: -x[1]):
        print(f"    {k:<18} {v:>5}")

    print()
    print("  Severities:")
    for k, v in sorted(by_severity.items(), key=lambda x: -x[1])[:12]:
        print(f"    {k:<24} {v:>5}")

    if pressure_buckets:
        print()
        print("  Sell-pressure recommendations:")
        for k, v in sorted(pressure_buckets.items(), key=lambda x: -x[1]):
            print(f"    {k:<24} {v:>5}")


def summarize_recent_samples(buy_rows, pos_rows):
    section("Recent intelligence samples")

    scored_buys = [r for r in buy_rows if get(r, "buy_opportunity_score") is not None]
    high_buys = sorted(scored_buys, key=lambda r: float(get(r, "buy_opportunity_score") or 0), reverse=True)[:10]

    print("  Top scored BUY rows:")
    if not high_buys:
        print("    None yet.")
    else:
        print(f"    {'Time':<19} {'Sym':<6} {'Appr':<5} {'Score':>5} {'Rec':<22} {'Setup':<30}")
        for r in high_buys:
            print(
                f"    {get(r, 'timestamp'):<19} {get(r, 'symbol'):<6} {str(get(r, 'approved')):<5} "
                f"{float(get(r, 'buy_opportunity_score') or 0):>5.1f} "
                f"{str(get(r, 'buy_opportunity_recommendation') or '-'):<22} "
                f"{short(get(r, 'setup_label') or '-', 30):<30}"
            )

    print()
    print("  Highest sell-pressure rows:")
    pressure_rows = [r for r in pos_rows if get(r, "sell_pressure_score") is not None]
    high_pressure = sorted(pressure_rows, key=lambda r: float(get(r, "sell_pressure_score") or 0), reverse=True)[:10]

    if not high_pressure:
        print("    None yet.")
    else:
        print(f"    {'Time':<19} {'Sym':<6} {'Action':<15} {'Score':>6} {'Rec':<24} {'UPL%':>8}")
        for r in high_pressure:
            print(
                f"    {get(r, 'timestamp'):<19} {get(r, 'symbol'):<6} {str(get(r, 'action') or '-'):<15} "
                f"{float(get(r, 'sell_pressure_score') or 0):>6.1f} "
                f"{str(get(r, 'sell_pressure_recommendation') or '-'):<24} "
                f"{float(get(r, 'unrealized_plpc') or 0):>8.2f}"
            )


def summarize_sells(rows):
    section("Sell rows / exit context")

    if not rows:
        print("  No sell rows.")
        return

    pnl_cols = ["realized_pnl", "realized_pl", "profit_loss", "pnl"]
    pnl_values = []

    for r in rows:
        for col in pnl_cols:
            val = get(r, col)
            if val is not None:
                try:
                    pnl_values.append(float(val))
                    break
                except Exception:
                    pass

    print(f"  Sell rows             : {len(rows)}")
    if pnl_values:
        print(f"  Sum available P&L     : ${sum(pnl_values):.2f}")
        print(f"  Avg available P&L     : ${sum(pnl_values) / len(pnl_values):.2f}")
    else:
        print("  Realized P&L summary  : no realized P&L column populated/available")

    print()
    print(f"  {'Time':<19} {'Sym':<6} {'Approved':<8} {'Fill':>10} Reason")
    print(f"  {'-'*19} {'-'*6} {'-'*8} {'-'*10} {'-'*60}")

    for r in rows[-15:]:
        print(
            f"  {get(r, 'timestamp'):<19} {get(r, 'symbol'):<6} {str(get(r, 'approved')):<8} "
            f"{str(get(r, 'fill_price') or '-') :>10} {short(get(r, 'rejection_reason'), 60)}"
        )


def main():
    target_date = sys.argv[1] if len(sys.argv) > 1 else date.today().isoformat()

    print("=" * 100)
    print(f"  Strategy Intelligence Report — {target_date}")
    print("=" * 100)

    buy_rows, buy_cols = fetch_buy_rows(repo, target_date)
    sell_rows, sell_cols = fetch_sell_rows(repo, target_date)
    pos_rows, pos_cols = fetch_position_momentum_rows(repo, target_date)

    summarize_buy_opportunity(buy_rows)
    summarize_setup_labels(buy_rows)
    summarize_rejections(buy_rows)
    summarize_replacement_intelligence(buy_rows, pos_rows)
    summarize_position_momentum(pos_rows)
    summarize_recent_samples(buy_rows, pos_rows)
    summarize_sells(sell_rows)

    print()
    print("Schema notes:")
    print(f"  trades BUY columns used              : {', '.join(buy_cols)}")
    print(f"  trades SELL columns used             : {', '.join(sell_cols)}")
    print(f"  position_momentum columns used       : {', '.join(pos_cols)}")
    print()
    print("Notes:")
    print("  - BUY score is observe-only until explicitly wired into sizing/approval.")
    print("  - Sell pressure may be live only when POSITION_MOMENTUM_USE_SELL_PRESSURE=true.")
    print("  - Older rows from before today’s patches may not have score fields populated.")


if __name__ == "__main__":
    main()
