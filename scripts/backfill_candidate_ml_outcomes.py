#!/usr/bin/env python3
"""Backfill forward outcomes for ML-bearing candidate_universe rows.

This is a narrow, local-data updater for the ML authority evidence path. It
targets candidate rows that already contain layered ML fields but do not yet
carry forward-return labels. Price paths are built from local feature_snapshots
only; the script does not call external market-data APIs.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
from pathlib import Path
from typing import Any

from services.intelligence.candidates.outcome_backfill import compute_candidate_outcome


def _load_json(raw: Any) -> dict[str, Any]:
    if not raw:
        return {}
    try:
        payload = json.loads(str(raw))
    except (TypeError, ValueError, json.JSONDecodeError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _fetch_target_rows(
    con: sqlite3.Connection,
    target_date: str,
    *,
    limit: int | None,
    overwrite: bool,
) -> list[sqlite3.Row]:
    clauses = [
        "substr(candidate_ts, 1, 10) = ?",
        "candidate_json LIKE '%layered_ml_final_instruction%'",
    ]
    params: list[Any] = [target_date]
    if not overwrite:
        clauses.append("candidate_json NOT LIKE '%forward_return_pct%'")
    sql = f"""
        SELECT id, candidate_ts, symbol, action, candidate_json
        FROM candidate_universe
        WHERE {" AND ".join(clauses)}
        ORDER BY candidate_ts ASC, id ASC
    """
    if limit:
        sql += " LIMIT ?"
        params.append(int(limit))
    return list(con.execute(sql, params))


def _fetch_feature_snapshot_bars(
    con: sqlite3.Connection,
    symbol: str,
    target_date: str,
) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT timestamp, last_price
        FROM feature_snapshots
        WHERE UPPER(symbol) = ?
          AND timestamp >= ?
          AND timestamp < ?
          AND last_price IS NOT NULL
          AND last_price > 0
        ORDER BY timestamp ASC
        """,
        (symbol.upper(), target_date, _next_date(target_date)),
    ).fetchall()
    bars = []
    for row in rows:
        price = float(row["last_price"])
        bars.append(
            {
                "timestamp": row["timestamp"],
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "source": "feature_snapshots_last_price",
            }
        )
    return bars


def _candidate_quote_price(payload: dict[str, Any]) -> float | None:
    candidate = payload.get("candidate") if isinstance(payload.get("candidate"), dict) else {}
    for source in (candidate, payload):
        for key in ("current_price", "mid", "reference_price", "signal_price", "price"):
            value = source.get(key)
            try:
                if value not in (None, "") and float(value) > 0:
                    return float(value)
            except (TypeError, ValueError):
                pass
    bid = candidate.get("bid", payload.get("bid"))
    ask = candidate.get("ask", payload.get("ask"))
    try:
        bid_f = float(bid)
        ask_f = float(ask)
    except (TypeError, ValueError):
        return None
    if bid_f > 0 and ask_f > 0:
        return (bid_f + ask_f) / 2.0
    return None


def _fetch_candidate_quote_bars(
    con: sqlite3.Connection,
    symbol: str,
    target_date: str,
) -> list[dict[str, Any]]:
    rows = con.execute(
        """
        SELECT candidate_ts, candidate_json
        FROM candidate_universe
        WHERE UPPER(symbol) = ?
          AND candidate_ts >= ?
          AND candidate_ts < ?
        ORDER BY candidate_ts ASC, id ASC
        """,
        (symbol.upper(), target_date, _next_date(target_date)),
    ).fetchall()
    bars = []
    for row in rows:
        price = _candidate_quote_price(_load_json(row["candidate_json"]))
        if price is None or price <= 0:
            continue
        bars.append(
            {
                "timestamp": row["candidate_ts"],
                "open": price,
                "high": price,
                "low": price,
                "close": price,
                "source": "candidate_universe_quote_path",
            }
        )
    return bars


def _next_date(target_date: str) -> str:
    from datetime import date, timedelta

    return (date.fromisoformat(target_date) + timedelta(days=1)).isoformat()


def _coverage_counts(con: sqlite3.Connection, target_date: str) -> dict[str, int]:
    row = con.execute(
        """
        SELECT
            COUNT(*) AS rows,
            SUM(CASE WHEN candidate_json LIKE '%layered_ml_final_instruction%' THEN 1 ELSE 0 END)
                AS ml_rows,
            SUM(CASE WHEN candidate_json LIKE '%layered_ml_final_instruction%'
                      AND candidate_json LIKE '%forward_return_pct%' THEN 1 ELSE 0 END)
                AS ml_rows_with_forward
        FROM candidate_universe
        WHERE substr(candidate_ts, 1, 10) = ?
        """,
        (target_date,),
    ).fetchone()
    return {
        "rows": int(row["rows"] or 0),
        "ml_rows": int(row["ml_rows"] or 0),
        "ml_rows_with_forward": int(row["ml_rows_with_forward"] or 0),
    }


def backfill(
    db_path: Path,
    target_date: str,
    *,
    limit: int | None = None,
    dry_run: bool = False,
    overwrite: bool = False,
) -> dict[str, Any]:
    con = sqlite3.connect(db_path, timeout=30)
    con.row_factory = sqlite3.Row
    con.execute("PRAGMA busy_timeout=30000")
    try:
        before = _coverage_counts(con, target_date)
        rows = _fetch_target_rows(con, target_date, limit=limit, overwrite=overwrite)
        bars_by_symbol: dict[str, list[dict[str, Any]]] = {}
        updates: list[tuple[str, int]] = []
        counts = {
            "eligible": len(rows),
            "updated": 0,
            "dry_run": int(bool(dry_run)),
            "no_bars": 0,
            "partial": 0,
            "labeled": 0,
            "pending": 0,
            "error": 0,
        }
        for row in rows:
            symbol = str(row["symbol"]).upper()
            try:
                if symbol not in bars_by_symbol:
                    bars_by_symbol[symbol] = _fetch_feature_snapshot_bars(
                        con,
                        symbol,
                        target_date,
                    )
                    if not bars_by_symbol[symbol]:
                        bars_by_symbol[symbol] = _fetch_candidate_quote_bars(
                            con,
                            symbol,
                            target_date,
                        )
                outcome = compute_candidate_outcome(dict(row), bars_by_symbol[symbol])
                if bars_by_symbol[symbol]:
                    outcome["candidate_outcome_price_path_source"] = (
                        bars_by_symbol[symbol][0].get("source")
                    )
                payload = _load_json(row["candidate_json"])
                payload.update(outcome)
                status = str(outcome.get("label_status") or "unknown")
                if status in counts:
                    counts[status] += 1
                if not dry_run:
                    updates.append(
                        (
                            json.dumps(payload, sort_keys=True, separators=(",", ":")),
                            int(row["id"]),
                        )
                    )
                counts["updated"] += 1
            except Exception:
                counts["error"] += 1
        if updates:
            con.executemany(
                "UPDATE candidate_universe SET candidate_json = ? WHERE id = ?",
                updates,
            )
            con.commit()
        after = _coverage_counts(con, target_date)
    finally:
        con.close()
    return {"date": target_date, "before": before, "after": after, **counts}


def _pct(num: int, den: int) -> str:
    return f"{100.0 * num / den:.1f}%" if den else "0.0%"


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("target_date")
    parser.add_argument("--db", default=os.getenv("TRADES_DB_PATH", "trades.db"))
    parser.add_argument("--limit", type=int, default=None)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--overwrite", action="store_true")
    args = parser.parse_args()

    result = backfill(
        Path(args.db),
        args.target_date,
        limit=args.limit,
        dry_run=args.dry_run,
        overwrite=args.overwrite,
    )
    before = result["before"]
    after = result["after"]
    print("=" * 72)
    print(f"  ML Candidate Forward Outcome Backfill - {result['date']}")
    print("=" * 72)
    print(f"dry_run              : {bool(result['dry_run'])}")
    print(f"eligible             : {result['eligible']}")
    print(f"updated              : {result['updated']}")
    print(f"labeled              : {result['labeled']}")
    print(f"partial              : {result['partial']}")
    print(f"pending              : {result['pending']}")
    print(f"no_bars              : {result['no_bars']}")
    print(f"error                : {result['error']}")
    print()
    print(
        "ml_forward_before   : "
        f"{before['ml_rows_with_forward']} / {before['ml_rows']} "
        f"({_pct(before['ml_rows_with_forward'], before['ml_rows'])})"
    )
    print(
        "ml_forward_after    : "
        f"{after['ml_rows_with_forward']} / {after['ml_rows']} "
        f"({_pct(after['ml_rows_with_forward'], after['ml_rows'])})"
    )
    return 1 if result["error"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
