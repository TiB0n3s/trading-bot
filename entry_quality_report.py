#!/usr/bin/env python3
"""Post-session entry-quality validation report.

Read-only. Segments matched BUY outcomes by observe-only entry intelligence
fields captured in decision_snapshots.
"""

from __future__ import annotations

import argparse
from collections import defaultdict
from statistics import mean

from db import DB_PATH, get_connection

MIN_BUCKET_SAMPLE = 20


def _bucket_extension(value):
    if value is None:
        return "unknown"
    value = float(value)
    if value > 3.5:
        return ">3.5"
    if value < 2.0:
        return "<2.0"
    return "2.0-3.5"


def _bucket_prior(value):
    if value is None:
        return "unknown"
    return ">3.0" if float(value) > 3.0 else "<=3.0"


def _rows(target_date: str):
    with get_connection(DB_PATH) as con:
        return con.execute(
            """
            SELECT ds.symbol,
                   ds.decision_time,
                   ds.momentum_state,
                   ds.volume_state,
                   ds.extension_from_recent_base_pct,
                   ds.rolling_special_labels,
                   ds.prior_session_return_pct,
                   ds.prior_session_participated,
                   ds.tape_label_at_signal,
                   ds.tape_bar_age_seconds,
                   mt.realized_pnl_pct,
                   mt.won
            FROM decision_snapshots ds
            JOIN trades t ON t.id = ds.trade_id
            JOIN matched_trades mt
              ON mt.symbol = t.symbol
             AND mt.entry_timestamp = t.timestamp
            WHERE substr(ds.decision_time, 1, 10) = ?
              AND lower(ds.action) = 'buy'
              AND ds.approved = 1
              AND mt.realized_pnl_pct IS NOT NULL
            ORDER BY ds.decision_time ASC, ds.symbol ASC
            """,
            (target_date,),
        ).fetchall()


def _summarize(rows, key_fn):
    buckets = defaultdict(list)
    for row in rows:
        buckets[key_fn(row)].append(float(row["realized_pnl_pct"]))
    return buckets


def _print_bucket_table(title, buckets):
    print()
    print("-" * 72)
    print(title)
    print("-" * 72)
    print(f"{'Bucket':<32} {'N':>5} {'AvgPnL%':>10} {'Status':<20}")
    for bucket in sorted(buckets):
        values = buckets[bucket]
        status = "ok" if len(values) >= MIN_BUCKET_SAMPLE else "insufficient_data"
        print(f"{str(bucket):<32} {len(values):>5} {mean(values):>10.3f} {status:<20}")


def report(target_date: str) -> int:
    rows = _rows(target_date)

    print("=" * 72)
    print(f"Entry Quality Report - {target_date}")
    print("=" * 72)
    print("Read-only: no gates are enforced by this report.")
    print(f"Matched approved BUY entries: {len(rows)}")
    print(f"Minimum sample per claim: {MIN_BUCKET_SAMPLE}")

    if not rows:
        print("[INFO] No matched BUY outcomes available yet.")
        return 0

    _print_bucket_table(
        "Outcome By Momentum State",
        _summarize(rows, lambda r: r["momentum_state"] or "unknown"),
    )
    _print_bucket_table(
        "Outcome By Volume State",
        _summarize(rows, lambda r: r["volume_state"] or "unknown"),
    )
    _print_bucket_table(
        "Outcome By Extension From Recent Base",
        _summarize(rows, lambda r: _bucket_extension(r["extension_from_recent_base_pct"])),
    )
    _print_bucket_table(
        "Outcome By Prior Session Return",
        _summarize(rows, lambda r: _bucket_prior(r["prior_session_return_pct"])),
    )
    _print_bucket_table(
        "Strong Prior Session + Pullback In Uptrend",
        _summarize(
            rows,
            lambda r: (
                "prior>3 + pullback"
                if (r["prior_session_return_pct"] is not None)
                and float(r["prior_session_return_pct"]) > 3.0
                and "pullback_in_uptrend" in str(r["rolling_special_labels"] or "")
                else "other"
            ),
        ),
    )

    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Market date YYYY-MM-DD")
    args = parser.parse_args()
    return report(args.date)


if __name__ == "__main__":
    raise SystemExit(main())
