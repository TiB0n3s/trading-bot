#!/usr/bin/env python3
from __future__ import annotations

import sqlite3

from db import DB_PATH, get_connection
from setup_engine import classify_setup


def load_rows_missing_setup(limit: int = 5000) -> list[sqlite3.Row]:
    with get_connection(DB_PATH) as con:
        rows = con.execute(
            """
            SELECT
                id,
                timestamp,
                symbol,
                market_session,
                market_bias,
                trend_direction,
                trend_strength,
                relative_strength_5m,
                distance_from_vwap,
                ret_5m,
                ret_15m,
                bar_timeframe,
                bar_count
            FROM feature_snapshots
            WHERE setup_label IS NULL
               OR setup_recommendation IS NULL
               OR setup_score IS NULL
               OR setup_confidence IS NULL
               OR setup_key IS NULL
            ORDER BY id ASC
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return rows


def update_setup_fields(row: sqlite3.Row) -> None:
    snapshot = dict(row)
    setup = classify_setup(snapshot)

    with get_connection(DB_PATH) as con:
        con.execute(
            """
            UPDATE feature_snapshots
            SET
                setup_label = ?,
                setup_recommendation = ?,
                setup_score = ?,
                setup_confidence = ?,
                setup_key = ?
            WHERE id = ?
            """,
            (
                setup.setup_label,
                setup.recommendation,
                setup.setup_score,
                setup.confidence,
                setup.setup_key,
                row["id"],
            ),
        )


def main() -> int:
    rows = load_rows_missing_setup(limit=100000)
    if not rows:
        print("No feature_snapshots rows need setup backfill.")
        return 0

    updated = 0
    failed = 0

    for row in rows:
        try:
            update_setup_fields(row)
            updated += 1
        except Exception as e:
            failed += 1
            print(f"Failed snapshot id={row['id']} symbol={row['symbol']}: {e}")

    print(f"Setup backfill complete: updated={updated}, failed={failed}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())