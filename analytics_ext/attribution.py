#!/usr/bin/env python3
"""
Attribution analytics helpers.

Read-only utilities for summarizing matched trade outcomes by decision context.

This is the foundation for the future learning loop:
- which setup types work?
- which risk levels underperform?
- which trader-brain scores correlate with better outcomes?
"""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from db import DB_PATH, get_connection


def safe_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except Exception:
        return default


def table_exists(table_name: str, db_path=DB_PATH) -> bool:
    with get_connection(db_path) as con:
        row = con.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name = ?",
            (table_name,),
        ).fetchone()
    return row is not None


def fetch_matched_trades(
    date_prefix: str | None = None,
    db_path=DB_PATH,
) -> list[dict[str, Any]]:
    """Return matched trades as dictionaries, optionally filtered by exit date."""
    if not table_exists("matched_trades", db_path):
        return []

    where = ""
    params: list[Any] = []

    if date_prefix:
        where = "WHERE exit_timestamp LIKE ?"
        params.append(f"{date_prefix}%")

    with get_connection(db_path) as con:
        rows = con.execute(
            f"""
            SELECT *
            FROM matched_trades
            {where}
            ORDER BY exit_timestamp ASC
            """,
            params,
        ).fetchall()

    return [dict(r) for r in rows]


def summarize_group(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Summarize P&L/win-rate/expectancy for a group of matched trades."""
    count = len(rows)
    pnl = sum(safe_float(r.get("realized_pnl")) for r in rows)
    wins = sum(1 for r in rows if safe_float(r.get("realized_pnl")) > 0)
    losses = sum(1 for r in rows if safe_float(r.get("realized_pnl")) < 0)
    flats = count - wins - losses
    win_rate = wins / count * 100 if count else 0.0
    expectancy = pnl / count if count else 0.0

    gross_profit = sum(
        safe_float(r.get("realized_pnl"))
        for r in rows
        if safe_float(r.get("realized_pnl")) > 0
    )
    gross_loss = abs(sum(
        safe_float(r.get("realized_pnl"))
        for r in rows
        if safe_float(r.get("realized_pnl")) < 0
    ))

    if gross_loss > 0:
        profit_factor: float | str = round(gross_profit / gross_loss, 4)
    elif gross_profit > 0:
        profit_factor = "inf"
    else:
        profit_factor = None

    return {
        "trades": count,
        "pnl": round(pnl, 2),
        "wins": wins,
        "losses": losses,
        "flats": flats,
        "win_rate": round(win_rate, 2),
        "expectancy": round(expectancy, 4),
        "gross_profit": round(gross_profit, 2),
        "gross_loss": round(gross_loss, 2),
        "profit_factor": profit_factor,
    }


def summarize_by_field(
    field: str,
    rows: list[dict[str, Any]],
) -> dict[str, dict[str, Any]]:
    """Summarize matched trade outcomes grouped by one field."""
    groups: dict[str, list[dict[str, Any]]] = defaultdict(list)

    for row in rows:
        key = row.get(field)
        if key is None or key == "":
            key = "missing"
        groups[str(key)].append(row)

    return {
        key: summarize_group(group_rows)
        for key, group_rows in sorted(groups.items())
    }


def attribution_summary(
    date_prefix: str | None = None,
    db_path=DB_PATH,
) -> dict[str, Any]:
    """Return multi-field attribution summary for matched trades."""
    rows = fetch_matched_trades(date_prefix=date_prefix, db_path=db_path)

    fields = [
        "symbol",
        "macro_regime",
        "market_bias",
        "risk_level",
        "entry_quality",
        "trend_direction",
        "trend_strength",
        "trader_brain_setup_type",
        "trader_brain_approved",
    ]

    return {
        "date_prefix": date_prefix,
        "overall": summarize_group(rows),
        "by_field": {
            field: summarize_by_field(field, rows)
            for field in fields
        },
    }
