#!/usr/bin/env python3
"""
Persist rolling_momentum.json into historical_trend_context.

This bridges the gap between rolling_momentum.py output and
experience_model.py trend blending.
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

from db import DB_PATH, get_connection


def ensure_historical_trend_context_table(db_path: Path | str = DB_PATH) -> None:
    with get_connection(db_path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS historical_trend_context (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                market_date TEXT NOT NULL,
                symbol TEXT NOT NULL,
                benchmark_symbol TEXT,
                close_price REAL,
                benchmark_close REAL,
                trend_1d_pct REAL,
                trend_3d_pct REAL,
                trend_5d_pct REAL,
                trend_10d_pct REAL,
                trend_20d_pct REAL,
                benchmark_1d_pct REAL,
                benchmark_5d_pct REAL,
                relative_strength_1d_pct REAL,
                relative_strength_5d_pct REAL,
                relative_strength_score REAL,
                sma_5 REAL,
                sma_10 REAL,
                sma_20 REAL,
                above_sma_5 INTEGER,
                above_sma_10 INTEGER,
                above_sma_20 INTEGER,
                distance_from_sma_20_pct REAL,
                volatility_5d_pct REAL,
                avg_range_5d_pct REAL,
                gap_pct REAL,
                higher_highs_3d INTEGER,
                higher_lows_3d INTEGER,
                lower_highs_3d INTEGER,
                lower_lows_3d INTEGER,
                trend_label TEXT,
                trend_regime TEXT,
                trend_confidence TEXT,
                trend_reason TEXT,
                raw_json TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE(market_date, symbol)
            )
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_historical_trend_context_date_symbol
            ON historical_trend_context(market_date, symbol)
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_historical_trend_context_symbol_date
            ON historical_trend_context(symbol, market_date)
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_historical_trend_context_label
            ON historical_trend_context(trend_label, trend_regime)
            """
        )


def _regime(label: str | None) -> str:
    label = (label or "").lower()
    if "strong_bullish" in label:
        return "strong_bullish"
    if "bullish" in label:
        return "bullish"
    if "bearish" in label:
        return "bearish"
    if "mixed" in label or "neutral" in label:
        return "mixed"
    return "unknown"


def _confidence(entry: dict) -> str:
    days = entry.get("market_days_found") or 0
    score = abs(float(entry.get("continuation_score") or 0))
    if days >= 5 and score >= 3:
        return "medium"
    if days >= 3:
        return "low"
    return "low"


def _trend_reason(entry: dict) -> str:
    reasons = entry.get("reasons") or []
    specials = entry.get("special_labels") or []
    parts = []
    if reasons:
        parts.append("reasons=" + ",".join(map(str, reasons)))
    if specials:
        parts.append("specials=" + ",".join(map(str, specials)))
    return "; ".join(parts) if parts else "rolling_momentum snapshot"


def build(date: str, input_path: str = "rolling_momentum.json") -> int:
    ensure_historical_trend_context_table(DB_PATH)
    p = Path(input_path)
    data = json.loads(p.read_text())

    symbols = data.get("symbols") or {}
    now = datetime.now(timezone.utc).replace(microsecond=0).isoformat()

    rows = []
    for sym, entry in symbols.items():
        if not isinstance(entry, dict):
            continue

        entry_date = str(entry.get("today") or date)
        if entry_date != date:
            continue

        trend_label = entry.get("trend_context")
        raw = json.dumps(entry, sort_keys=True)

        rows.append(
            {
                "market_date": date,
                "symbol": sym.upper(),
                "benchmark_symbol": "QQQ",
                "close_price": entry.get("latest_price"),
                "benchmark_close": None,
                "trend_1d_pct": entry.get("prior_day_return_pct"),
                "trend_3d_pct": None,
                "trend_5d_pct": entry.get("five_day_return_pct"),
                "trend_10d_pct": None,
                "trend_20d_pct": None,
                "benchmark_1d_pct": None,
                "benchmark_5d_pct": None,
                "relative_strength_1d_pct": None,
                "relative_strength_5d_pct": None,
                "relative_strength_score": entry.get("continuation_score"),
                "sma_5": None,
                "sma_10": None,
                "sma_20": None,
                "above_sma_5": None,
                "above_sma_10": None,
                "above_sma_20": None,
                "distance_from_sma_20_pct": None,
                "volatility_5d_pct": None,
                "avg_range_5d_pct": None,
                "gap_pct": entry.get("overnight_gap_pct"),
                "higher_highs_3d": None,
                "higher_lows_3d": None,
                "lower_highs_3d": None,
                "lower_lows_3d": None,
                "trend_label": trend_label,
                "trend_regime": _regime(trend_label),
                "trend_confidence": _confidence(entry),
                "trend_reason": _trend_reason(entry),
                "raw_json": raw,
                "created_at": now,
                "updated_at": now,
            }
        )

    if not rows:
        print(f"No rolling momentum rows found for {date} in {input_path}")
        return 0

    cols = list(rows[0].keys())
    placeholders = ", ".join("?" for _ in cols)
    update_cols = [c for c in cols if c not in ("market_date", "symbol", "created_at")]
    update_clause = ", ".join(f"{c}=excluded.{c}" for c in update_cols)

    sql = f"""
    INSERT INTO historical_trend_context ({", ".join(cols)})
    VALUES ({placeholders})
    ON CONFLICT(market_date, symbol) DO UPDATE SET
      {update_clause}
    """

    with get_connection(DB_PATH) as con:
        con.executemany(sql, [[row[c] for c in cols] for row in rows])
        con.commit()

    print(f"Wrote historical_trend_context rows: {len(rows)} for {date}")
    return len(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--date", required=True)
    ap.add_argument("--input", default="rolling_momentum.json")
    args = ap.parse_args()

    build(args.date, args.input)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
