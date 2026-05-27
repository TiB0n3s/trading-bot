#!/usr/bin/env python3
"""
Prediction validation report - read-only.

Compares observe-only daily_symbol_predictions with same-day outcomes when
those outcomes exist. Before the session, it serves as a readiness report.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
from typing import Any

from db import DB_PATH, get_connection


def table_exists(con, table_name: str) -> bool:
    row = con.execute(
        """
        SELECT 1
        FROM sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table_name,),
    ).fetchone()
    return row is not None


def fmt(value: Any, digits: int = 2) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value):.{digits}f}"
    except Exception:
        return str(value)


def money(value: Any) -> str:
    if value is None:
        return "-"
    try:
        value = float(value)
        sign = "+" if value >= 0 else ""
        return f"{sign}${value:.2f}"
    except Exception:
        return str(value)


def bucket_for_score(score: Any) -> str:
    if score is None:
        return "unknown"
    score = float(score)
    if score >= 55:
        return "high_55_plus"
    if score >= 50:
        return "mid_50_55"
    if score >= 45:
        return "low_45_50"
    return "weak_below_45"


def avg(values) -> float | None:
    nums = [float(v) for v in values if v is not None]
    return sum(nums) / len(nums) if nums else None


def load_predictions(con, target_date: str):
    if not table_exists(con, "daily_symbol_predictions"):
        return []
    return con.execute(
        """
        SELECT market_date, symbol, prediction_score, probability_of_profit,
               probability_of_order, expected_pnl, confidence, sample_size,
               timing_score, recommended_entry_timing, trend_score,
               trend_label, trend_regime, trend_confidence, reason
        FROM daily_symbol_predictions
        WHERE market_date = ?
        ORDER BY prediction_score DESC, symbol
        """,
        (target_date,),
    ).fetchall()


def load_signal_outcomes(con, target_date: str) -> dict[str, Any]:
    if not table_exists(con, "historical_signal_outcomes"):
        return {}
    rows = con.execute(
        """
        SELECT symbol,
               COUNT(*) AS signals,
               SUM(CASE WHEN approved = 1 THEN 1 ELSE 0 END) AS approved,
               SUM(CASE WHEN approved = 0 THEN 1 ELSE 0 END) AS rejected,
               SUM(CASE WHEN realized_pnl IS NOT NULL THEN 1 ELSE 0 END) AS closed_signals,
               SUM(COALESCE(realized_pnl, 0)) AS realized_pnl,
               AVG(realized_pnl) AS avg_realized_pnl
        FROM historical_signal_outcomes
        WHERE market_date = ?
        GROUP BY symbol
        """,
        (target_date,),
    ).fetchall()
    return {r["symbol"]: dict(r) for r in rows}


def load_matched_trades(con, target_date: str) -> dict[str, Any]:
    if not table_exists(con, "matched_trades"):
        return {}
    rows = con.execute(
        """
        SELECT symbol,
               COUNT(*) AS matched_trades,
               SUM(COALESCE(realized_pnl, 0)) AS realized_pnl,
               AVG(realized_pnl) AS avg_realized_pnl,
               SUM(CASE WHEN won = 1 THEN 1 ELSE 0 END) AS wins,
               SUM(CASE WHEN won = 0 THEN 1 ELSE 0 END) AS losses
        FROM matched_trades
        WHERE date(exit_timestamp) = ?
        GROUP BY symbol
        """,
        (target_date,),
    ).fetchall()
    return {r["symbol"]: dict(r) for r in rows}


def load_strong_day_participation(con, target_date: str) -> dict[str, Any]:
    if not table_exists(con, "strong_day_participation"):
        return {}
    rows = con.execute(
        """
        SELECT *
        FROM strong_day_participation
        WHERE market_date = ?
          AND min_session_pct = (
              SELECT MIN(min_session_pct)
              FROM strong_day_participation
              WHERE market_date = ?
          )
        """,
        (target_date, target_date),
    ).fetchall()
    return {r["symbol"]: dict(r) for r in rows}


def section(title: str) -> None:
    print()
    print("-" * 72)
    print(title)
    print("-" * 72)


def render_distribution(predictions) -> None:
    section("Prediction Distribution")
    buckets = defaultdict(list)
    for row in predictions:
        buckets[bucket_for_score(row["prediction_score"])].append(row)

    print(f"{'Bucket':<18} {'N':>4} {'AvgScore':>9} {'AvgTiming':>9} {'AvgTrend':>9}")
    for bucket in ("high_55_plus", "mid_50_55", "low_45_50", "weak_below_45", "unknown"):
        rows = buckets.get(bucket) or []
        if not rows:
            continue
        print(
            f"{bucket:<18} {len(rows):>4} "
            f"{fmt(avg([r['prediction_score'] for r in rows])):>9} "
            f"{fmt(avg([r['timing_score'] for r in rows])):>9} "
            f"{fmt(avg([r['trend_score'] for r in rows])):>9}"
        )


def render_top_bottom(predictions, limit: int = 8) -> None:
    section("Top Predictions")
    print(f"{'Sym':<7} {'Score':>7} {'Timing':>7} {'Trend':>7} {'Conf':<9} Reason")
    for row in predictions[:limit]:
        print(
            f"{row['symbol']:<7} "
            f"{fmt(row['prediction_score']):>7} "
            f"{fmt(row['timing_score'], 0):>7} "
            f"{fmt(row['trend_score'], 0):>7} "
            f"{str(row['confidence'] or '-'):<9} "
            f"{str(row['reason'] or '-')[:80]}"
        )

    section("Weakest Predictions")
    print(f"{'Sym':<7} {'Score':>7} {'Timing':>7} {'Trend':>7} {'Conf':<9} Reason")
    for row in reversed(predictions[-limit:]):
        print(
            f"{row['symbol']:<7} "
            f"{fmt(row['prediction_score']):>7} "
            f"{fmt(row['timing_score'], 0):>7} "
            f"{fmt(row['trend_score'], 0):>7} "
            f"{str(row['confidence'] or '-'):<9} "
            f"{str(row['reason'] or '-')[:80]}"
        )


def render_outcome_buckets(predictions, signals, matched) -> None:
    section("Outcome By Prediction Bucket")
    if not signals and not matched:
        print("No same-day signal/trade outcomes yet. Re-run after the session.")
        return

    buckets = defaultdict(list)
    for row in predictions:
        buckets[bucket_for_score(row["prediction_score"])].append(row)

    print(
        f"{'Bucket':<18} {'N':>4} {'Signals':>7} {'Appr':>6} "
        f"{'SigPnL':>10} {'Matches':>7} {'MatchPnL':>10}"
    )
    for bucket in ("high_55_plus", "mid_50_55", "low_45_50", "weak_below_45", "unknown"):
        rows = buckets.get(bucket) or []
        if not rows:
            continue
        symbols = [r["symbol"] for r in rows]
        signal_count = sum((signals.get(s) or {}).get("signals") or 0 for s in symbols)
        approved = sum((signals.get(s) or {}).get("approved") or 0 for s in symbols)
        signal_pnl = sum((signals.get(s) or {}).get("realized_pnl") or 0 for s in symbols)
        match_count = sum((matched.get(s) or {}).get("matched_trades") or 0 for s in symbols)
        match_pnl = sum((matched.get(s) or {}).get("realized_pnl") or 0 for s in symbols)
        print(
            f"{bucket:<18} {len(rows):>4} {signal_count:>7} {approved:>6} "
            f"{money(signal_pnl):>10} {match_count:>7} {money(match_pnl):>10}"
        )


def render_strong_day_buckets(predictions, strong_days) -> None:
    section("Strong-Day Participation By Prediction Bucket")
    if not strong_days:
        print("No strong_day_participation rows yet. Run strong_day_participation_report.py --write-db after the session.")
        return

    buckets = defaultdict(list)
    for row in predictions:
        buckets[bucket_for_score(row["prediction_score"])].append(row)

    print(
        f"{'Bucket':<18} {'N':>4} {'Strong':>7} {'Particip':>8} "
        f"{'Missed':>7} {'AutoCand':>8} {'AvgStrong%':>10}"
    )
    for bucket in ("high_55_plus", "mid_50_55", "low_45_50", "weak_below_45", "unknown"):
        rows = buckets.get(bucket) or []
        if not rows:
            continue
        symbols = [r["symbol"] for r in rows]
        tracked_rows = [
            strong_days.get(s)
            for s in symbols
            if strong_days.get(s) and strong_days[s]["session_return_pct"] is not None
        ]
        strong_rows = [
            r for r in tracked_rows
            if float(r["session_return_pct"] or 0) >= float(r["min_session_pct"] or 0)
        ]
        participated = sum(
            1 for r in strong_rows
            if r["primary_status"] in ("full_participation", "partial_participation", "auto_buy_participation")
        )
        missed = sum(
            1 for r in strong_rows
            if r["primary_status"] in ("no_signals", "no_buy_signals", "sell_only_signals", "all_rejected", "auto_buy_candidate_only")
        )
        auto_candidates = sum(1 for r in strong_rows if int(r["auto_buy_candidate_count"] or 0) > 0)
        avg_strong = avg([r["session_return_pct"] for r in strong_rows])
        print(
            f"{bucket:<18} {len(rows):>4} {len(strong_rows):>7} {participated:>8} "
            f"{missed:>7} {auto_candidates:>8} {fmt(avg_strong):>10}"
        )

    section("Top Strong Days Versus Predictions")
    ranked = sorted(
        [
            r for r in strong_days.values()
            if r["session_return_pct"] is not None
            and float(r["session_return_pct"] or 0) >= float(r["min_session_pct"] or 0)
        ],
        key=lambda r: float(r["session_return_pct"] or 0),
        reverse=True,
    )
    print(f"{'Sym':<7} {'Strong%':>8} {'Pred':>7} {'Status':<24} {'Source':<18} {'Blocker':<24}")
    for r in ranked[:12]:
        print(
            f"{r['symbol']:<7} "
            f"{fmt(r['session_return_pct']):>8} "
            f"{fmt(r['prediction_score']):>7} "
            f"{str(r['primary_status'] or '-'):<24} "
            f"{str(r['signal_source'] or '-'):<18} "
            f"{str(r['primary_blocker'] or '-'):<24}"
        )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("date_arg", nargs="?")
    parser.add_argument("--date", dest="date_opt")
    args = parser.parse_args()

    target_date = args.date_opt or args.date_arg or date.today().isoformat()

    print("=" * 72)
    print(f"Prediction Validation - {target_date}")
    print("=" * 72)
    print("Read-only: predictions remain observe-only and do not affect trading.")

    with get_connection(DB_PATH) as con:
        predictions = load_predictions(con, target_date)
        signals = load_signal_outcomes(con, target_date)
        matched = load_matched_trades(con, target_date)
        strong_days = load_strong_day_participation(con, target_date)

    print()
    print(f"Predictions          : {len(predictions)}")
    print(f"Symbols with signals : {len(signals)}")
    print(f"Symbols with matches : {len(matched)}")
    print(f"Strong-day rows      : {len(strong_days)}")

    if not predictions:
        print("[FAIL] No daily_symbol_predictions rows found for this date.")
        return 1

    if not signals and not matched:
        print("[OK] Pre-session readiness mode: predictions exist; outcomes are not populated yet.")

    render_distribution(predictions)
    render_top_bottom(predictions)
    render_outcome_buckets(predictions, signals, matched)
    render_strong_day_buckets(predictions, strong_days)

    print()
    print("[OK] prediction validation report completed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
