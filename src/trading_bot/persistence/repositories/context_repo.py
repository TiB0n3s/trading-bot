"""Repository for context/status database reads and core table setup."""

from __future__ import annotations

from db import (
    DB_PATH,
    get_connection,
)
from db import (
    ensure_recent_favorable_setups_table as _ensure_recent_favorable_setups_table,
)
from db import (
    get_recent_favorable_setup as _get_recent_favorable_setup,
)
from db import (
    init_db_performance_indexes as _init_db_performance_indexes,
)
from db import (
    prune_recent_favorable_setups as _prune_recent_favorable_setups,
)
from db import (
    upsert_recent_favorable_setup as _upsert_recent_favorable_setup,
)
from repositories.trade_accounting import fill_bearing_order_condition


def init_core_tables(db_path=DB_PATH) -> None:
    with get_connection(db_path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS trades (
                id                INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp         TEXT NOT NULL,
                symbol            TEXT,
                action            TEXT,
                signal_price      REAL,
                approved          INTEGER,
                rejection_reason  TEXT,
                confidence        TEXT,
                position_size_pct REAL,
                stop_loss_pct     REAL,
                take_profit_pct   REAL,
                order_id          TEXT,
                order_status      TEXT,
                qty               INTEGER,
                fill_price        REAL
            )
            """
        )

        con.execute(
            """
            CREATE TABLE IF NOT EXISTS cooldowns (
                symbol          TEXT NOT NULL,
                action          TEXT NOT NULL,
                last_order_time TEXT NOT NULL,
                PRIMARY KEY (symbol, action)
            )
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS recent_sells (
                symbol          TEXT PRIMARY KEY,
                last_sell_time  TEXT NOT NULL,
                last_sell_price REAL NOT NULL
            )
            """
        )


def ensure_recent_favorable_setups_table() -> None:
    _ensure_recent_favorable_setups_table()


def upsert_recent_favorable_setup(
    *,
    symbol: str,
    observed_at: str,
    setup_label: str | None,
    setup_policy_action: str | None,
) -> None:
    _upsert_recent_favorable_setup(
        symbol=symbol,
        observed_at=observed_at,
        setup_label=setup_label,
        setup_policy_action=setup_policy_action,
    )


def get_recent_favorable_setup(symbol: str, ttl_minutes: int = 15):
    return _get_recent_favorable_setup(symbol, ttl_minutes=ttl_minutes)


def prune_recent_favorable_setups(ttl_minutes: int = 15) -> None:
    _prune_recent_favorable_setups(ttl_minutes=ttl_minutes)


def init_db_performance_indexes(db_path=DB_PATH) -> None:
    _init_db_performance_indexes(db_path)


def startup_db_open_symbols(db_path=DB_PATH):
    fill_bearing = fill_bearing_order_condition()
    with get_connection(db_path) as con:
        return con.execute(
            f"""
            SELECT symbol,
                   SUM(CASE WHEN action='buy' THEN qty ELSE -qty END) AS net_qty
            FROM trades
            WHERE {fill_bearing}
              AND order_id IS NOT NULL
            GROUP BY symbol
            HAVING net_qty > 0
            """
        ).fetchall()


def session_momentum_summary(db_path=DB_PATH) -> dict:
    with get_connection(db_path) as con:
        rows = con.execute(
            """
            SELECT trend_label, COUNT(*) AS n
            FROM session_momentum
            GROUP BY trend_label
            ORDER BY n DESC
            """
        ).fetchall()
    return {(r["trend_label"] or "unknown"): r["n"] for r in rows}


def session_momentum_snapshot(limit=40, db_path=DB_PATH) -> list[dict]:
    with get_connection(db_path) as con:
        rows = con.execute(
            """
            SELECT symbol, updated_at, trend_label, trend_score,
                   session_return_pct, momentum_5m_pct,
                   momentum_15m_pct, momentum_30m_pct,
                   distance_from_vwap_pct, reason
            FROM session_momentum
            ORDER BY symbol
            LIMIT ?
            """,
            (limit,),
        ).fetchall()
    return [dict(r) for r in rows]


def symbol_intelligence_rows(market_date: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT
                symbol,
                prediction_score,
                probability_of_profit,
                probability_of_order,
                expected_pnl,
                expected_win_rate,
                confidence,
                sample_size,
                reason,
                timing_score,
                recommended_entry_timing,
                recommended_exit_timing,
                historical_timing_sample_size,
                timing_reason,
                trend_score,
                trend_label,
                trend_regime,
                trend_confidence,
                trend_similarity_sample_size,
                trend_reason,
                updated_at
            FROM daily_symbol_predictions
            WHERE market_date = ?
            ORDER BY symbol
            """,
            (market_date,),
        ).fetchall()
