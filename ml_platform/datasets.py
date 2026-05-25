"""Read-only dataset profiling helpers."""

from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from db import DB_PATH
from ml_platform.config import FEATURE_VERSION


def _table_exists(con: sqlite3.Connection, table: str) -> bool:
    row = con.execute(
        "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    return row is not None


def _count(con: sqlite3.Connection, table: str, where_sql: str = "", params=()) -> int | None:
    if not _table_exists(con, table):
        return None
    sql = f"SELECT COUNT(*) AS n FROM {table}"
    if where_sql:
        sql += f" WHERE {where_sql}"
    return int(con.execute(sql, params).fetchone()["n"] or 0)


def _min_max(con: sqlite3.Connection, table: str, column: str) -> dict[str, Any]:
    if not _table_exists(con, table):
        return {"min": None, "max": None}
    row = con.execute(
        f"SELECT MIN({column}) AS min_value, MAX({column}) AS max_value FROM {table}"
    ).fetchone()
    return {"min": row["min_value"], "max": row["max_value"]}


def dataset_profile(
    *,
    db_path: Path | str = DB_PATH,
    start_date: str | None = None,
    end_date: str | None = None,
) -> dict[str, Any]:
    """Return a read-only profile of ML-relevant tables."""
    db_path = Path(db_path)
    date_where = ""
    params: tuple[str, ...] = ()

    if start_date and end_date:
        date_where = "substr(timestamp, 1, 10) BETWEEN ? AND ?"
        params = (start_date, end_date)
    elif start_date or end_date:
        raise ValueError("Provide both start_date and end_date, or neither")

    with sqlite3.connect(f"file:{db_path}?mode=ro", uri=True) as con:
        con.row_factory = sqlite3.Row

        snapshots = _count(con, "feature_snapshots", date_where, params)
        labels = None
        if _table_exists(con, "labeled_setups"):
            if date_where:
                labels = _count(con, "labeled_setups", date_where, params)
            else:
                labels = _count(con, "labeled_setups")

        matched_trades = _count(con, "matched_trades")
        context_rows = _count(con, "daily_symbol_context")
        event_rows = _count(con, "daily_symbol_events")
        prediction_rows = _count(con, "daily_symbol_predictions")

        symbols = 0
        if _table_exists(con, "feature_snapshots"):
            where = f"WHERE {date_where}" if date_where else ""
            row = con.execute(
                f"SELECT COUNT(DISTINCT symbol) AS n FROM feature_snapshots {where}",
                params,
            ).fetchone()
            symbols = int(row["n"] or 0)

        snapshot_range = _min_max(con, "feature_snapshots", "timestamp")

    label_coverage = (
        round((labels / snapshots) * 100.0, 2)
        if snapshots and labels is not None
        else 0.0
    )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "db_path": str(db_path),
        "feature_version": FEATURE_VERSION,
        "start_date": start_date,
        "end_date": end_date,
        "tables": {
            "feature_snapshots": snapshots,
            "labeled_setups": labels,
            "matched_trades": matched_trades,
            "daily_symbol_context": context_rows,
            "daily_symbol_events": event_rows,
            "daily_symbol_predictions": prediction_rows,
        },
        "feature_snapshots_range": snapshot_range,
        "distinct_snapshot_symbols": symbols,
        "label_coverage_pct": label_coverage,
        "ready_for_training": bool(snapshots and labels and snapshots >= 500 and label_coverage >= 50.0),
        "notes": [
            "Profile is read-only.",
            "Training is not recommended below 500 labeled snapshots.",
            "Predictions remain observe-only.",
        ],
    }


def write_profile(profile: dict[str, Any], output: Path | str) -> Path:
    path = Path(output)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(profile, indent=2, sort_keys=True) + "\n")
    return path
