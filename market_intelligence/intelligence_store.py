#!/usr/bin/env python3
"""
Persistent market-intelligence storage.

Purpose:
- Store one daily symbol context row per symbol per market date.
- Store structured news/event/fundamental rows that can later be joined to trades.
- Keep the learning loop separate from live trading decisions at first.

These tables are append/update analytical storage only. They do not place orders.
"""

import json
from datetime import datetime
from pathlib import Path

from db import DB_PATH, get_connection


DAILY_SYMBOL_CONTEXT_COLUMNS = [
    "market_date",
    "symbol",
    "source",
    "macro_sentiment",
    "macro_regime",
    "risk_multiplier",
    "max_new_positions",
    "block_new_buys",

    "bias",
    "confidence",
    "fundamental_score",
    "risk_level",
    "entry_quality",
    "avoid_type",
    "reason",

    "daily_pct",
    "intraday_pct",
    "momentum_30m_pct",
    "last_price",
    "bar_count_1m",

    "catalyst_score",
    "relative_strength_score",
    "sector_alignment",
    "index_alignment",
    "liquidity_quality",
    "volume_context",
    "price_location",

    "business_quality_score",
    "growth_score",
    "debt_risk_score",
    "management_score",
    "industry_health_score",
    "economic_risk_score",
    "political_risk_score",
    "geopolitical_risk_score",
    "cultural_risk_score",

    "consumer_appetite_score",
    "revenue_impact_score",
    "profit_potential_score",
    "margin_risk_score",
    "supply_chain_risk_score",
    "materials_risk_score",
    "competitive_risk_score",
    "execution_risk_score",

    "raw_json",
    "created_at",
    "updated_at",
]


def init_intelligence_tables(db_path: Path | str = DB_PATH) -> None:
    """Create intelligence tables and indexes. Safe to run repeatedly."""
    with get_connection(db_path) as con:
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


def _num(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _int(value):
    if value is None:
        return None
    if isinstance(value, bool):
        return int(value)
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _text(value):
    if value is None:
        return None
    return str(value)


def context_row_from_market_context(ctx: dict, symbol: str) -> dict:
    """Build one daily_symbol_context row from market_context.json content."""
    symbols = ctx.get("symbols") or {}
    entry = symbols.get(symbol) or {}

    data_snapshot = entry.get("data_snapshot") or {}

    now = datetime.now().isoformat(timespec="seconds")

    row = {
        "market_date": ctx.get("market_date"),
        "symbol": symbol,
        "source": ctx.get("source"),

        "macro_sentiment": ctx.get("macro_sentiment"),
        "macro_regime": ctx.get("macro_regime"),
        "risk_multiplier": _num(ctx.get("risk_multiplier")),
        "max_new_positions": _int(ctx.get("max_new_positions")),
        "block_new_buys": _int(ctx.get("block_new_buys")),

        "bias": entry.get("bias"),
        "confidence": entry.get("confidence"),
        "fundamental_score": entry.get("fundamental_score"),
        "risk_level": entry.get("risk_level"),
        "entry_quality": entry.get("entry_quality"),
        "avoid_type": entry.get("avoid_type"),
        "reason": entry.get("reason"),

        "daily_pct": _num(data_snapshot.get("daily_pct") or entry.get("daily_pct")),
        "intraday_pct": _num(data_snapshot.get("intraday_pct") or entry.get("intraday_pct")),
        "momentum_30m_pct": _num(data_snapshot.get("momentum_30m_pct") or entry.get("momentum_30m_pct")),
        "last_price": _num(data_snapshot.get("last_price") or entry.get("last_price")),
        "bar_count_1m": _int(data_snapshot.get("bar_count_1m") or entry.get("bar_count_1m")),

        "catalyst_score": _num(entry.get("catalyst_score")),
        "relative_strength_score": _num(entry.get("relative_strength_score")),
        "sector_alignment": _text(entry.get("sector_alignment")),
        "index_alignment": _text(entry.get("index_alignment")),
        "liquidity_quality": _text(entry.get("liquidity_quality")),
        "volume_context": _text(entry.get("volume_context")),
        "price_location": _text(entry.get("price_location")),

        "business_quality_score": _num(entry.get("business_quality_score")),
        "growth_score": _num(entry.get("growth_score")),
        "debt_risk_score": _num(entry.get("debt_risk_score")),
        "management_score": _num(entry.get("management_score")),
        "industry_health_score": _num(entry.get("industry_health_score")),
        "economic_risk_score": _num(entry.get("economic_risk_score")),
        "political_risk_score": _num(entry.get("political_risk_score")),
        "geopolitical_risk_score": _num(entry.get("geopolitical_risk_score")),
        "cultural_risk_score": _num(entry.get("cultural_risk_score")),

        "consumer_appetite_score": _num(entry.get("consumer_appetite_score")),
        "revenue_impact_score": _num(entry.get("revenue_impact_score")),
        "profit_potential_score": _num(entry.get("profit_potential_score")),
        "margin_risk_score": _num(entry.get("margin_risk_score")),
        "supply_chain_risk_score": _num(entry.get("supply_chain_risk_score")),
        "materials_risk_score": _num(entry.get("materials_risk_score")),
        "competitive_risk_score": _num(entry.get("competitive_risk_score")),
        "execution_risk_score": _num(entry.get("execution_risk_score")),

        "raw_json": json.dumps(entry, sort_keys=True),
        "created_at": now,
        "updated_at": now,
    }

    return row


def upsert_daily_symbol_context(row: dict, db_path: Path | str = DB_PATH) -> None:
    """Insert/update one daily symbol context row."""
    cols = DAILY_SYMBOL_CONTEXT_COLUMNS
    insert_cols = ", ".join(cols)
    placeholders = ", ".join(["?"] * len(cols))

    update_cols = [c for c in cols if c not in ("market_date", "symbol", "created_at")]
    update_sql = ", ".join([f"{c}=excluded.{c}" for c in update_cols])

    values = [row.get(c) for c in cols]

    with get_connection(db_path) as con:
        con.execute(
            f"""
            INSERT INTO daily_symbol_context ({insert_cols})
            VALUES ({placeholders})
            ON CONFLICT(market_date, symbol)
            DO UPDATE SET {update_sql}
            """,
            values,
        )


def ingest_market_context(path: Path | str, db_path: Path | str = DB_PATH) -> dict:
    """Ingest a market_context-style JSON file into daily_symbol_context."""
    init_intelligence_tables(db_path)

    path = Path(path)
    ctx = json.loads(path.read_text())

    market_date = ctx.get("market_date")
    symbols = ctx.get("symbols") or {}

    if not market_date:
        raise ValueError(f"{path} missing market_date")

    inserted = 0
    for symbol in sorted(symbols):
        row = context_row_from_market_context(ctx, symbol)
        upsert_daily_symbol_context(row, db_path=db_path)
        inserted += 1

    return {
        "path": str(path),
        "market_date": market_date,
        "symbols": inserted,
        "source": ctx.get("source"),
    }


def insert_daily_symbol_event(event: dict, db_path: Path | str = DB_PATH) -> int:
    """Insert one structured event/news/fundamental row."""
    init_intelligence_tables(db_path)

    now = datetime.now().isoformat(timespec="seconds")
    row = {
        "market_date": event.get("market_date"),
        "symbol": event.get("symbol"),
        "event_type": event.get("event_type"),
        "event_subtype": event.get("event_subtype"),
        "event_summary": event.get("event_summary"),
        "source": event.get("source"),
        "source_url": event.get("source_url"),
        "product_name": event.get("product_name"),
        "company_segment": event.get("company_segment"),
        "industry": event.get("industry"),
        "expected_market_impact": event.get("expected_market_impact"),
        "trade_relevance": event.get("trade_relevance"),
        "time_horizon": event.get("time_horizon"),
        "confidence": event.get("confidence"),
        "consumer_appetite_score": _num(event.get("consumer_appetite_score")),
        "revenue_impact_score": _num(event.get("revenue_impact_score")),
        "profit_potential_score": _num(event.get("profit_potential_score")),
        "margin_risk_score": _num(event.get("margin_risk_score")),
        "supply_chain_risk_score": _num(event.get("supply_chain_risk_score")),
        "materials_risk_score": _num(event.get("materials_risk_score")),
        "regulatory_risk_score": _num(event.get("regulatory_risk_score")),
        "competitive_risk_score": _num(event.get("competitive_risk_score")),
        "execution_risk_score": _num(event.get("execution_risk_score")),
        "macro_risk_score": _num(event.get("macro_risk_score")),
        "raw_json": json.dumps(event, sort_keys=True),
        "created_at": now,
        "updated_at": now,
    }

    required = ("market_date", "symbol", "event_type")
    missing = [k for k in required if not row.get(k)]
    if missing:
        raise ValueError(f"event missing required fields: {missing}")

    cols = list(row)
    placeholders = ", ".join(["?"] * len(cols))

    with get_connection(db_path) as con:
        cur = con.execute(
            f"""
            INSERT INTO daily_symbol_events ({", ".join(cols)})
            VALUES ({placeholders})
            """,
            [row[c] for c in cols],
        )
        return int(cur.lastrowid)


EVENT_SCORE_FIELDS = [
    "consumer_appetite_score",
    "revenue_impact_score",
    "profit_potential_score",
    "margin_risk_score",
    "supply_chain_risk_score",
    "materials_risk_score",
    "competitive_risk_score",
    "execution_risk_score",
]


def _avg(values):
    nums = []
    for v in values:
        try:
            if v is not None:
                nums.append(float(v))
        except (TypeError, ValueError):
            pass
    return round(sum(nums) / len(nums), 2) if nums else None


def _max(values):
    nums = []
    for v in values:
        try:
            if v is not None:
                nums.append(float(v))
        except (TypeError, ValueError):
            pass
    return round(max(nums), 2) if nums else None


def aggregate_symbol_events(market_date: str, symbol: str, db_path: Path | str = DB_PATH) -> dict:
    """Aggregate daily_symbol_events into one learnable symbol-level score set.

    Upside fields are averaged because multiple bullish events should not
    unrealistically stack forever.

    Risk fields use max because one serious supply-chain/regulatory/execution
    risk is enough to matter.
    """
    with get_connection(db_path) as con:
        events = con.execute(
            """
            SELECT *
            FROM daily_symbol_events
            WHERE market_date = ?
              AND symbol = ?
            """,
            (market_date, symbol),
        ).fetchall()

    if not events:
        return {
            "market_date": market_date,
            "symbol": symbol,
            "event_count": 0,
            "has_events": False,
        }

    upside_fields = [
        "consumer_appetite_score",
        "revenue_impact_score",
        "profit_potential_score",
    ]
    risk_fields = [
        "margin_risk_score",
        "supply_chain_risk_score",
        "materials_risk_score",
        "competitive_risk_score",
        "execution_risk_score",
    ]

    out = {
        "market_date": market_date,
        "symbol": symbol,
        "event_count": len(events),
        "has_events": True,
    }

    for field in upside_fields:
        out[field] = _avg([e[field] for e in events])

    for field in risk_fields:
        out[field] = _max([e[field] for e in events])

    # Catalyst score balances upside and confidence against risk.
    upside = _avg([
        out.get("consumer_appetite_score"),
        out.get("revenue_impact_score"),
        out.get("profit_potential_score"),
    ]) or 0

    risk = _avg([
        out.get("margin_risk_score"),
        out.get("supply_chain_risk_score"),
        out.get("materials_risk_score"),
        out.get("competitive_risk_score"),
        out.get("execution_risk_score"),
    ]) or 0

    out["catalyst_score"] = round(max(0, min(100, upside - (risk * 0.35) + 20)), 2)

    impacts = [e["expected_market_impact"] for e in events if e["expected_market_impact"]]
    relevance = [e["trade_relevance"] for e in events if e["trade_relevance"]]

    out["event_impacts"] = ", ".join(sorted(set(impacts))) if impacts else None
    out["event_relevance"] = ", ".join(sorted(set(relevance))) if relevance else None

    return out


def update_daily_context_from_events(market_date: str, symbol: str | None = None, db_path: Path | str = DB_PATH) -> dict:
    """Update daily_symbol_context rows with aggregate event scores.

    If symbol is None, update all symbols present in daily_symbol_context for
    the market date.
    """
    init_intelligence_tables(db_path)

    with get_connection(db_path) as con:
        if symbol:
            symbols = [symbol.upper()]
        else:
            rows = con.execute(
                """
                SELECT symbol
                FROM daily_symbol_context
                WHERE market_date = ?
                ORDER BY symbol
                """,
                (market_date,),
            ).fetchall()
            symbols = [r["symbol"] for r in rows]

    updated = 0
    skipped = 0
    summaries = []

    for sym in symbols:
        agg = aggregate_symbol_events(market_date, sym, db_path=db_path)

        if not agg.get("has_events"):
            skipped += 1
            continue

        with get_connection(db_path) as con:
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
                    datetime.now().isoformat(timespec="seconds"),
                    market_date,
                    sym,
                ),
            )

        updated += 1
        summaries.append(agg)

    return {
        "market_date": market_date,
        "symbol": symbol.upper() if symbol else None,
        "updated": updated,
        "skipped_no_events": skipped,
        "summaries": summaries,
    }
