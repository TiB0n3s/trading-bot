#!/usr/bin/env python3
"""Compare auto-buy candidates with forward feature-snapshot returns.

This report is read-only. It uses the feature snapshot table as the first
available forward-price source so the internal/bar-only cohort can be compared
against TradingView-triggered signals without placing additional trades.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date
from pathlib import Path
from statistics import mean
from typing import Any

from db import DB_PATH, get_connection


BASE_DIR = Path(__file__).resolve().parent
HORIZONS = (5, 15, 30, 60)


def _table_exists(con, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _price_at_or_before(con, symbol: str, ts: str) -> tuple[float | None, str | None]:
    row = con.execute(
        """
        SELECT last_price, timestamp
        FROM feature_snapshots
        WHERE symbol = ?
          AND julianday(timestamp) <= julianday(?)
          AND last_price IS NOT NULL
        ORDER BY julianday(timestamp) DESC, id DESC
        LIMIT 1
        """,
        (symbol, ts),
    ).fetchone()
    if not row:
        return None, None
    return float(row["last_price"]), row["timestamp"]


def _price_at_or_after(con, symbol: str, ts: str, minutes: int) -> tuple[float | None, str | None]:
    row = con.execute(
        """
        SELECT last_price, timestamp
        FROM feature_snapshots
        WHERE symbol = ?
          AND julianday(timestamp) >= julianday(?, ?)
          AND last_price IS NOT NULL
        ORDER BY julianday(timestamp) ASC, id ASC
        LIMIT 1
        """,
        (symbol, ts, f"+{minutes} minutes"),
    ).fetchone()
    if not row:
        return None, None
    return float(row["last_price"]), row["timestamp"]


def _pct(start: float | None, end: float | None) -> float | None:
    if start is None or end is None or start <= 0:
        return None
    return (end - start) / start * 100.0


def candidate_outcomes(target_date: str, db_path: Path | str = DB_PATH) -> list[dict[str, Any]]:
    with get_connection(db_path) as con:
        if not _table_exists(con, "auto_buy_candidates") or not _table_exists(con, "feature_snapshots"):
            return []
        candidates = con.execute(
            """
            SELECT *
            FROM auto_buy_candidates
            WHERE substr(timestamp, 1, 10) = ?
            ORDER BY timestamp, id
            """,
            (target_date,),
        ).fetchall()

        out = []
        for row in candidates:
            item = dict(row)
            base_price, base_ts = _price_at_or_before(con, item["symbol"], item["timestamp"])
            item["base_price"] = base_price
            item["base_timestamp"] = base_ts
            for minutes in HORIZONS:
                future_price, future_ts = _price_at_or_after(con, item["symbol"], item["timestamp"], minutes)
                item[f"price_{minutes}m"] = future_price
                item[f"timestamp_{minutes}m"] = future_ts
                item[f"return_{minutes}m"] = _pct(base_price, future_price)
            out.append(item)
    return out


def tradingview_signal_summary(target_date: str, db_path: Path | str = DB_PATH) -> dict[str, Any]:
    with get_connection(db_path) as con:
        if not _table_exists(con, "trades"):
            return {}
        rows = con.execute(
            """
            SELECT
                COUNT(*) AS n,
                SUM(CASE WHEN approved = 1 THEN 1 ELSE 0 END) AS approved,
                SUM(CASE WHEN approved = 0 THEN 1 ELSE 0 END) AS rejected
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
            """,
            (target_date,),
        ).fetchone()

        rejected = {}
        if _table_exists(con, "rejected_signal_outcomes"):
            rejected_rows = con.execute(
                """
                SELECT action,
                       COUNT(*) AS n,
                       AVG(return_15m) AS avg15,
                       AVG(return_60m) AS avg60,
                       AVG(max_favorable_60m) AS mfe60,
                       AVG(max_adverse_60m) AS mae60
                FROM rejected_signal_outcomes
                WHERE substr(timestamp, 1, 10) = ?
                  AND label_status IN ('labeled', 'partial')
                GROUP BY action
                ORDER BY action
                """,
                (target_date,),
            ).fetchall()
            rejected = {row["action"]: dict(row) for row in rejected_rows}

    return {
        "signals": int(rows["n"] or 0),
        "approved": int(rows["approved"] or 0),
        "rejected": int(rows["rejected"] or 0),
        "rejected_outcomes": rejected,
    }


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.3f}%"
    return str(value)


def _summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[tuple[str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[(row.get("signal_source") or "unknown", row.get("decision") or "unknown")].append(row)

    summary = []
    for (source, decision), items in sorted(groups.items()):
        line: dict[str, Any] = {"source": source, "decision": decision, "n": len(items)}
        for minutes in HORIZONS:
            vals = [r[f"return_{minutes}m"] for r in items if r.get(f"return_{minutes}m") is not None]
            line[f"avg_return_{minutes}m"] = mean(vals) if vals else None
            line[f"labeled_{minutes}m"] = len(vals)
        summary.append(line)
    return summary


def _score_bucket(score: float | None) -> str:
    if score is None:
        return "missing"
    if score >= 16:
        return "16+"
    if score >= 13:
        return "13-15"
    if score >= 10:
        return "10-12"
    if score >= 7:
        return "7-9"
    return "<7"


def _summarize_score_buckets(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        groups[_score_bucket(row.get("score"))].append(row)

    order = {"16+": 0, "13-15": 1, "10-12": 2, "7-9": 3, "<7": 4, "missing": 5}
    summary = []
    for bucket, items in sorted(groups.items(), key=lambda item: order.get(item[0], 99)):
        line: dict[str, Any] = {"bucket": bucket, "n": len(items)}
        for minutes in HORIZONS:
            vals = [r[f"return_{minutes}m"] for r in items if r.get(f"return_{minutes}m") is not None]
            line[f"avg_return_{minutes}m"] = mean(vals) if vals else None
            line[f"labeled_{minutes}m"] = len(vals)
        summary.append(line)
    return summary


def render(target_date: str, rows: list[dict[str, Any]], tv_summary: dict[str, Any]) -> bool:
    print("=" * 88)
    print(f"  Auto-Buy Outcome Report - {target_date}")
    print("=" * 88)

    if not rows:
        print("[WARN] no auto-buy candidates or feature snapshots found")
        return False

    print("Auto-buy candidate forward returns")
    for line in _summarize(rows):
        print(
            f"  {line['source']:<18} {line['decision']:<22} n={line['n']:<4} "
            f"5m={_fmt(line['avg_return_5m']):>9} ({line['labeled_5m']}) "
            f"15m={_fmt(line['avg_return_15m']):>9} ({line['labeled_15m']}) "
            f"30m={_fmt(line['avg_return_30m']):>9} ({line['labeled_30m']}) "
            f"60m={_fmt(line['avg_return_60m']):>9} ({line['labeled_60m']})"
        )

    print()
    print("Score buckets")
    for line in _summarize_score_buckets(rows):
        print(
            f"  score {line['bucket']:<7} n={line['n']:<4} "
            f"5m={_fmt(line['avg_return_5m']):>9} ({line['labeled_5m']}) "
            f"15m={_fmt(line['avg_return_15m']):>9} ({line['labeled_15m']}) "
            f"30m={_fmt(line['avg_return_30m']):>9} ({line['labeled_30m']}) "
            f"60m={_fmt(line['avg_return_60m']):>9} ({line['labeled_60m']})"
        )

    print()
    print("Top strong/watch candidates")
    ranked = [
        row for row in rows
        if row.get("decision") in ("strong_buy_candidate", "watch")
    ]
    ranked.sort(key=lambda r: (r.get("score") or 0, r.get("return_15m") or -999), reverse=True)
    for row in ranked[:15]:
        print(
            f"  {row['timestamp']} {row['symbol']:<6} {row['decision']:<22} "
            f"score={row['score']:<5} ret15={_fmt(row.get('return_15m')):>9} "
            f"ret60={_fmt(row.get('return_60m')):>9} order={row.get('order_id') or '-'}"
        )

    print()
    print("TradingView signal baseline")
    if tv_summary:
        print(
            f"  signals={tv_summary['signals']} approved={tv_summary['approved']} "
            f"rejected={tv_summary['rejected']}"
        )
        for action, line in (tv_summary.get("rejected_outcomes") or {}).items():
            print(
                f"  rejected {action:<4} n={line['n']:<4} "
                f"avg15={_fmt(line.get('avg15')):>9} avg60={_fmt(line.get('avg60')):>9} "
                f"mfe60={_fmt(line.get('mfe60')):>9} mae60={_fmt(line.get('mae60')):>9}"
            )
    else:
        print("  no trades table data")

    print()
    print("[OK] auto-buy outcome report completed")
    return True


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", default=date.today().isoformat())
    parser.add_argument("--db-path", default=str(DB_PATH))
    args = parser.parse_args()

    rows = candidate_outcomes(args.date, args.db_path)
    tv_summary = tradingview_signal_summary(args.date, args.db_path)
    return 0 if render(args.date, rows, tv_summary) else 1


if __name__ == "__main__":
    raise SystemExit(main())
