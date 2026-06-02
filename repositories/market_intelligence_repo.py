"""Repository boundary for market intelligence storage."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class MarketIntelligenceRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def init_tables(self) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_symbol_context (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    source TEXT,
                    macro_sentiment TEXT,
                    macro_regime TEXT,
                    risk_multiplier REAL,
                    max_new_positions INTEGER,
                    block_new_buys INTEGER,
                    bias TEXT,
                    confidence TEXT,
                    fundamental_score TEXT,
                    risk_level TEXT,
                    entry_quality TEXT,
                    avoid_type TEXT,
                    reason TEXT,
                    daily_pct REAL,
                    intraday_pct REAL,
                    momentum_30m_pct REAL,
                    last_price REAL,
                    bar_count_1m INTEGER,
                    catalyst_score REAL,
                    relative_strength_score REAL,
                    sector_alignment TEXT,
                    index_alignment TEXT,
                    liquidity_quality TEXT,
                    volume_context TEXT,
                    price_location TEXT,
                    business_quality_score REAL,
                    growth_score REAL,
                    debt_risk_score REAL,
                    management_score REAL,
                    industry_health_score REAL,
                    economic_risk_score REAL,
                    political_risk_score REAL,
                    geopolitical_risk_score REAL,
                    cultural_risk_score REAL,
                    consumer_appetite_score REAL,
                    revenue_impact_score REAL,
                    profit_potential_score REAL,
                    margin_risk_score REAL,
                    supply_chain_risk_score REAL,
                    materials_risk_score REAL,
                    competitive_risk_score REAL,
                    execution_risk_score REAL,
                    raw_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE(market_date, symbol)
                )
                """
            )
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS daily_symbol_events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    event_subtype TEXT,
                    event_summary TEXT,
                    source TEXT,
                    source_url TEXT,
                    product_name TEXT,
                    company_segment TEXT,
                    industry TEXT,
                    expected_market_impact TEXT,
                    trade_relevance TEXT,
                    time_horizon TEXT,
                    confidence TEXT,
                    consumer_appetite_score REAL,
                    revenue_impact_score REAL,
                    profit_potential_score REAL,
                    margin_risk_score REAL,
                    supply_chain_risk_score REAL,
                    materials_risk_score REAL,
                    regulatory_risk_score REAL,
                    competitive_risk_score REAL,
                    execution_risk_score REAL,
                    macro_risk_score REAL,
                    raw_json TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_daily_symbol_context_date_symbol
                ON daily_symbol_context(market_date, symbol)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_daily_symbol_context_symbol_date
                ON daily_symbol_context(symbol, market_date)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_daily_symbol_events_date_symbol
                ON daily_symbol_events(market_date, symbol)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_daily_symbol_events_type
                ON daily_symbol_events(event_type, market_date)
                """
            )

    def upsert_daily_symbol_context(self, row: dict[str, Any], columns: list[str]) -> None:
        insert_cols = ", ".join(columns)
        placeholders = ", ".join(["?"] * len(columns))
        update_cols = [c for c in columns if c not in ("market_date", "symbol", "created_at")]
        update_sql = ", ".join([f"{c}=excluded.{c}" for c in update_cols])
        values = [row.get(c) for c in columns]

        with get_connection(self.db_path) as con:
            con.execute(
                f"""
                INSERT INTO daily_symbol_context ({insert_cols})
                VALUES ({placeholders})
                ON CONFLICT(market_date, symbol)
                DO UPDATE SET {update_sql}
                """,
                values,
            )

    def insert_daily_symbol_event(self, row: dict[str, Any]) -> int:
        columns = list(row)
        placeholders = ", ".join(["?"] * len(columns))
        with get_connection(self.db_path) as con:
            cur = con.execute(
                f"""
                INSERT INTO daily_symbol_events ({", ".join(columns)})
                VALUES ({placeholders})
                """,
                [row[col] for col in columns],
            )
            return int(cur.lastrowid)

    def daily_symbol_events(self, market_date: str, symbol: str):
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT *
                FROM daily_symbol_events
                WHERE market_date = ?
                  AND symbol = ?
                """,
                (market_date, symbol),
            ).fetchall()

    def daily_symbol_events_for_context(self, market_date: str, symbol: str):
        symbol = symbol.upper().strip()
        linked_symbol_token = f'"{symbol}"'
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT *
                FROM daily_symbol_events
                WHERE market_date = ?
                  AND (
                    symbol = ?
                    OR (
                      raw_json LIKE ?
                      AND raw_json LIKE '%"context_only": true%'
                      AND raw_json LIKE '%"linked_symbols"%'
                    )
                  )
                ORDER BY
                  CASE WHEN symbol = ? THEN 0 ELSE 1 END,
                  id
                """,
                (market_date, symbol, f"%{linked_symbol_token}%", symbol),
            ).fetchall()

    def daily_symbol_event_keys(self, market_date: str) -> set[tuple[str, str, str, str]]:
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT symbol, event_type, event_summary, source_url
                FROM daily_symbol_events
                WHERE market_date = ?
                """,
                (market_date,),
            ).fetchall()
        return {
            (
                row["symbol"],
                row["event_type"],
                row["event_summary"] or "",
                row["source_url"] or "",
            )
            for row in rows
        }

    def context_symbols(self, market_date: str) -> list[str]:
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT symbol
                FROM daily_symbol_context
                WHERE market_date = ?
                ORDER BY symbol
                """,
                (market_date,),
            ).fetchall()
        return [row["symbol"] for row in rows]

    def context_summary_rows(self, market_date: str):
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT symbol, bias, confidence, risk_level, entry_quality
                FROM daily_symbol_context
                WHERE market_date = ?
                ORDER BY symbol
                """,
                (market_date,),
            ).fetchall()

    def context_exists(self, market_date: str, symbol: str) -> bool:
        with get_connection(self.db_path) as con:
            row = con.execute(
                """
                SELECT id
                FROM daily_symbol_context
                WHERE market_date = ?
                  AND symbol = ?
                """,
                (market_date, symbol),
            ).fetchone()
        return row is not None

    def update_context_event_scores(self, market_date: str, symbol: str, agg: dict[str, Any], updated_at: str) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                UPDATE daily_symbol_context
                SET
                    catalyst_score = ?,
                    consumer_appetite_score = ?,
                    revenue_impact_score = ?,
                    profit_potential_score = ?,
                    margin_risk_score = ?,
                    supply_chain_risk_score = ?,
                    materials_risk_score = ?,
                    competitive_risk_score = ?,
                    execution_risk_score = ?,
                    raw_json = ?,
                    updated_at = ?
                WHERE market_date = ?
                  AND symbol = ?
                """,
                (
                    agg.get("catalyst_score"),
                    agg.get("consumer_appetite_score"),
                    agg.get("revenue_impact_score"),
                    agg.get("profit_potential_score"),
                    agg.get("margin_risk_score"),
                    agg.get("supply_chain_risk_score"),
                    agg.get("materials_risk_score"),
                    agg.get("competitive_risk_score"),
                    agg.get("execution_risk_score"),
                    json.dumps(agg, sort_keys=True),
                    updated_at,
                    market_date,
                    symbol,
                ),
            )

    def insert_context_event_scores(
        self,
        market_date: str,
        symbol: str,
        agg: dict[str, Any],
        raw_json: str,
        timestamp: str,
    ) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                INSERT INTO daily_symbol_context (
                    market_date,
                    symbol,
                    source,
                    macro_sentiment,
                    macro_regime,
                    risk_multiplier,
                    max_new_positions,
                    block_new_buys,
                    bias,
                    confidence,
                    fundamental_score,
                    risk_level,
                    entry_quality,
                    avoid_type,
                    reason,
                    catalyst_score,
                    consumer_appetite_score,
                    revenue_impact_score,
                    profit_potential_score,
                    margin_risk_score,
                    supply_chain_risk_score,
                    materials_risk_score,
                    competitive_risk_score,
                    execution_risk_score,
                    raw_json,
                    created_at,
                    updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    market_date,
                    symbol,
                    "event_aggregate_seed",
                    "mixed",
                    "caution",
                    0.75,
                    6,
                    0,
                    "neutral",
                    "low",
                    "neutral",
                    "medium",
                    "conditional",
                    None,
                    "Seeded from event aggregates; market context builder should enrich full context.",
                    agg.get("catalyst_score"),
                    agg.get("consumer_appetite_score"),
                    agg.get("revenue_impact_score"),
                    agg.get("profit_potential_score"),
                    agg.get("margin_risk_score"),
                    agg.get("supply_chain_risk_score"),
                    agg.get("materials_risk_score"),
                    agg.get("competitive_risk_score"),
                    agg.get("execution_risk_score"),
                    raw_json,
                    timestamp,
                    timestamp,
                ),
            )
