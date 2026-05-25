#!/usr/bin/env python3
"""
Export a read-only ML research dataset from trades.db.

This script reads feature_snapshots and optional labels/context/predictions.
It does not train models, write to SQLite, place orders, or affect runtime
behavior.

Usage:
  python3 export_ml_dataset.py --date 2026-05-26 --output /tmp/ml_dataset.csv
  python3 export_ml_dataset.py --start-date 2026-05-20 --end-date 2026-05-26 --output /tmp/ml_dataset.csv
"""

from __future__ import annotations

import argparse
import csv
import json
import sqlite3
from pathlib import Path

from db import DB_PATH
from ml_platform.governance import build_dataset_manifest


BASE_COLUMNS = [
    "snapshot_id",
    "snapshot_date",
    "timestamp",
    "symbol",
    "last_price",
    "ret_1m",
    "ret_5m",
    "ret_15m",
    "range_pos_15m",
    "distance_from_5m_high",
    "distance_from_5m_low",
    "distance_from_vwap",
    "volume_ratio_5m",
    "benchmark_symbol",
    "benchmark_ret_5m",
    "relative_strength_5m",
    "spread_pct",
    "market_session",
    "macro_regime",
    "market_bias",
    "trend_direction",
    "trend_strength",
    "feature_available_at",
    "feature_generated_at",
    "feature_age_seconds",
    "source",
    "is_stale",
    "staleness_reason",
    "bar_timeframe",
    "bar_count",
    "setup_label",
    "setup_recommendation",
    "setup_score",
    "setup_confidence",
    "setup_key",
    "future_price_5m",
    "future_price_15m",
    "future_price_30m",
    "ret_fwd_5m",
    "ret_fwd_15m",
    "ret_fwd_30m",
    "max_up_15m",
    "max_down_15m",
    "outcome_label",
    "context_bias",
    "context_confidence",
    "context_risk_level",
    "context_entry_quality",
    "context_catalyst_score",
    "context_relative_strength_score",
    "context_sector_alignment",
    "context_index_alignment",
    "prediction_score",
    "probability_of_profit",
    "probability_of_order",
    "expected_pnl",
    "prediction_confidence",
    "prediction_sample_size",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", help="Single snapshot date, YYYY-MM-DD")
    parser.add_argument("--start-date", help="Start snapshot date, YYYY-MM-DD")
    parser.add_argument("--end-date", help="End snapshot date, YYYY-MM-DD")
    parser.add_argument("--output", required=True, help="CSV output path")
    parser.add_argument("--db-path", default=str(DB_PATH), help="SQLite DB path")
    parser.add_argument("--manifest-output", help="Optional JSON dataset manifest output path")
    parser.add_argument("--query-version", default="ml_dataset_export_v1")
    parser.add_argument("--label-version", default="label_taxonomy_v1")
    args = parser.parse_args()

    if args.date and (args.start_date or args.end_date):
        parser.error("Use either --date or --start-date/--end-date, not both")
    if not args.date and not (args.start_date and args.end_date):
        parser.error("Provide --date or both --start-date and --end-date")

    return args


def date_filter(args: argparse.Namespace) -> tuple[str, tuple[str, ...]]:
    if args.date:
        return "substr(fs.timestamp, 1, 10) = ?", (args.date,)
    return "substr(fs.timestamp, 1, 10) BETWEEN ? AND ?", (args.start_date, args.end_date)


def table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def table_columns(con: sqlite3.Connection, table: str) -> set[str]:
    if not table_exists(con, table):
        return set()
    return {row["name"] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}


def optional_column(columns: set[str], table_alias: str, column: str, fallback: str = "NULL") -> str:
    return f"{table_alias}.{column}" if column in columns else f"{fallback} AS {column}"


def fetch_rows(args: argparse.Namespace) -> list[sqlite3.Row]:
    db_path = Path(args.db_path)
    where_sql, params = date_filter(args)

    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row

        required = ("feature_snapshots", "labeled_setups")
        missing = [t for t in required if not table_exists(con, t)]
        if missing:
            raise SystemExit(f"Missing required table(s): {', '.join(missing)}")
        fs_columns = table_columns(con, "feature_snapshots")

        # Context/prediction tables are expected in normal operation, but left
        # joins keep this export useful during recovery or partial rebuilds.
        query = f"""
            SELECT
                fs.id AS snapshot_id,
                substr(fs.timestamp, 1, 10) AS snapshot_date,
                fs.timestamp,
                fs.symbol,
                fs.last_price,
                fs.ret_1m,
                fs.ret_5m,
                fs.ret_15m,
                fs.range_pos_15m,
                fs.distance_from_5m_high,
                fs.distance_from_5m_low,
                fs.distance_from_vwap,
                fs.volume_ratio_5m,
                fs.benchmark_symbol,
                fs.benchmark_ret_5m,
                fs.relative_strength_5m,
                fs.spread_pct,
                fs.market_session,
                fs.macro_regime,
                fs.market_bias,
                fs.trend_direction,
                fs.trend_strength,
                {optional_column(fs_columns, 'fs', 'feature_available_at', 'fs.timestamp')},
                {optional_column(fs_columns, 'fs', 'feature_generated_at', 'fs.timestamp')},
                {optional_column(fs_columns, 'fs', 'feature_age_seconds', '0')},
                {optional_column(fs_columns, 'fs', 'source', "'feature_snapshots_legacy'")},
                {optional_column(fs_columns, 'fs', 'is_stale', '0')},
                {optional_column(fs_columns, 'fs', 'staleness_reason')},
                fs.bar_timeframe,
                fs.bar_count,
                fs.setup_label,
                fs.setup_recommendation,
                fs.setup_score,
                fs.setup_confidence,
                fs.setup_key,
                ls.future_price_5m,
                ls.future_price_15m,
                ls.future_price_30m,
                ls.ret_fwd_5m,
                ls.ret_fwd_15m,
                ls.ret_fwd_30m,
                ls.max_up_15m,
                ls.max_down_15m,
                ls.outcome_label,
                c.bias AS context_bias,
                c.confidence AS context_confidence,
                c.risk_level AS context_risk_level,
                c.entry_quality AS context_entry_quality,
                c.catalyst_score AS context_catalyst_score,
                c.relative_strength_score AS context_relative_strength_score,
                c.sector_alignment AS context_sector_alignment,
                c.index_alignment AS context_index_alignment,
                p.prediction_score,
                p.probability_of_profit,
                p.probability_of_order,
                p.expected_pnl,
                p.confidence AS prediction_confidence,
                p.sample_size AS prediction_sample_size
            FROM feature_snapshots fs
            LEFT JOIN labeled_setups ls
              ON ls.snapshot_id = fs.id
            LEFT JOIN daily_symbol_context c
              ON c.market_date = substr(fs.timestamp, 1, 10)
             AND c.symbol = fs.symbol
            LEFT JOIN daily_symbol_predictions p
              ON p.market_date = substr(fs.timestamp, 1, 10)
             AND p.symbol = fs.symbol
            WHERE {where_sql}
            ORDER BY fs.timestamp, fs.symbol, fs.id
        """
        return con.execute(query, params).fetchall()


def write_csv(rows: list[sqlite3.Row], output: str) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)

    with path.open("w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=BASE_COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow({col: row[col] for col in BASE_COLUMNS})

    return path


def main() -> int:
    args = parse_args()
    rows = fetch_rows(args)
    path = write_csv(rows, args.output)
    manifest_path = None
    if args.manifest_output:
        manifest = build_dataset_manifest(
            db_path=args.db_path,
            start_date=args.date or args.start_date,
            end_date=args.date or args.end_date,
            query_version=args.query_version,
            label_version=args.label_version,
        )
        manifest_path = Path(args.manifest_output)
        manifest_path.parent.mkdir(parents=True, exist_ok=True)
        manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n")

    labeled = sum(1 for r in rows if r["outcome_label"] is not None)
    symbols = {r["symbol"] for r in rows}

    print("=== ML dataset export ===")
    print(f"output       : {path}")
    print(f"rows         : {len(rows)}")
    print(f"labeled_rows : {labeled}")
    print(f"symbols      : {len(symbols)}")
    if manifest_path:
        print(f"manifest     : {manifest_path}")

    if not rows:
        print("[WARN] no feature_snapshots matched the requested date range")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
