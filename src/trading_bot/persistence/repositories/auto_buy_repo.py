"""Repository helpers for auto-buy candidate persistence."""

from __future__ import annotations

import json
import sqlite3
from typing import Any

from db import DB_PATH, get_connection


def is_database_locked_error(exc: BaseException) -> bool:
    return isinstance(exc, sqlite3.OperationalError) and "database is locked" in str(exc).lower()


def init_tables(db_path=DB_PATH) -> None:
    with get_connection(db_path) as con:
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS auto_buy_candidates (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                signal_source TEXT,
                decision TEXT,
                score REAL,
                reason TEXT,
                market_bias TEXT,
                entry_quality TEXT,
                risk_level TEXT,
                session_trend_label TEXT,
                session_trend_score REAL,
                session_return_pct REAL,
                momentum_5m_pct REAL,
                momentum_15m_pct REAL,
                momentum_30m_pct REAL,
                distance_from_vwap_pct REAL,
                setup_label TEXT,
                setup_recommendation TEXT,
                setup_score REAL,
                hard_block_reason TEXT,
                feature_snapshot_id INTEGER,
                live_buy_enabled INTEGER DEFAULT 0,
                order_submitted INTEGER DEFAULT 0,
                order_id TEXT
            )
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_buy_candidates_timestamp
            ON auto_buy_candidates(timestamp)
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_buy_candidates_symbol
            ON auto_buy_candidates(symbol, timestamp)
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_buy_candidates_date_submitted
            ON auto_buy_candidates(substr(timestamp, 1, 10), order_submitted)
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_buy_candidates_symbol_date_decision_submitted
            ON auto_buy_candidates(symbol, substr(timestamp, 1, 10), decision, order_submitted)
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS auto_buy_decision_snapshots (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                candidate_timestamp TEXT NOT NULL,
                symbol TEXT NOT NULL,
                signal_source TEXT,
                decision TEXT,
                score REAL,
                reason TEXT,
                hard_block_reason TEXT,
                live_buy_enabled INTEGER,
                live_block_reason TEXT,
                risk_cross_check_reason TEXT,
                order_submitted INTEGER DEFAULT 0,
                order_id TEXT,
                order_status TEXT,
                candidate_json TEXT,
                order_json TEXT,
                runtime_effect TEXT NOT NULL DEFAULT 'auto_buy_paper_execution_path'
            )
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_buy_decision_snapshots_time
            ON auto_buy_decision_snapshots(candidate_timestamp)
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_buy_decision_snapshots_symbol_time
            ON auto_buy_decision_snapshots(symbol, candidate_timestamp)
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_buy_decision_snapshots_date
            ON auto_buy_decision_snapshots(substr(candidate_timestamp, 1, 10))
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS auto_buy_intraday_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                target_date TEXT NOT NULL,
                symbol TEXT,
                feedback_key TEXT NOT NULL,
                status TEXT NOT NULL,
                score_penalty REAL,
                hard_block_reason TEXT,
                evidence_json TEXT,
                candidate_json TEXT,
                runtime_effect TEXT NOT NULL
            )
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_buy_intraday_feedback_date_key
            ON auto_buy_intraday_feedback(target_date, feedback_key, created_at)
            """
        )
        con.execute(
            """
            CREATE TABLE IF NOT EXISTS auto_buy_historical_outcome_feedback (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                created_at TEXT NOT NULL,
                target_date TEXT NOT NULL,
                lookback_days INTEGER NOT NULL,
                feedback_key TEXT NOT NULL,
                status TEXT NOT NULL,
                trades INTEGER,
                wins INTEGER,
                losses INTEGER,
                loss_rate REAL,
                avg_pnl_pct REAL,
                min_pnl_pct REAL,
                max_pnl_pct REAL,
                symbols_json TEXT,
                sources_json TEXT,
                evidence_json TEXT,
                runtime_effect TEXT NOT NULL,
                UNIQUE(target_date, lookback_days, feedback_key)
            )
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_buy_historical_feedback_lookup
            ON auto_buy_historical_outcome_feedback(target_date, lookback_days, feedback_key)
            """
        )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_buy_historical_feedback_status
            ON auto_buy_historical_outcome_feedback(target_date, status, trades)
            """
        )
        existing_cols = {
            row["name"] for row in con.execute("PRAGMA table_info(auto_buy_candidates)").fetchall()
        }
        if "hard_block_reason" not in existing_cols:
            con.execute("ALTER TABLE auto_buy_candidates ADD COLUMN hard_block_reason TEXT")
        snapshot_cols = {
            row["name"]
            for row in con.execute("PRAGMA table_info(auto_buy_decision_snapshots)").fetchall()
        }
        snapshot_column_defaults = {
            "execution_status": "TEXT NOT NULL DEFAULT 'PENDING'",
            "routed_order_id": "TEXT",
            "execution_error": "TEXT",
            "execution_attempted_at": "TEXT",
            "execution_completed_at": "TEXT",
        }
        for column, column_type in snapshot_column_defaults.items():
            if column not in snapshot_cols:
                con.execute(
                    f"ALTER TABLE auto_buy_decision_snapshots ADD COLUMN {column} {column_type}"
                )
        con.execute(
            """
            CREATE INDEX IF NOT EXISTS idx_auto_buy_decision_snapshots_execution
            ON auto_buy_decision_snapshots(execution_status, decision, score, candidate_timestamp)
            """
        )


def table_exists(table_name: str, db_path=DB_PATH) -> bool:
    with get_connection(db_path) as con:
        row = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table_name,),
        ).fetchone()
    return row is not None


def table_columns(table_name: str, db_path=DB_PATH) -> set[str]:
    with get_connection(db_path) as con:
        rows = con.execute(f"PRAGMA table_info({table_name})").fetchall()
    return {row["name"] for row in rows}


def candidate_decision_rows(target_date: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT decision, COUNT(*) AS n, AVG(score) AS avg_score, MAX(score) AS max_score
            FROM auto_buy_candidates
            WHERE substr(timestamp, 1, 10) = ?
            GROUP BY decision
            ORDER BY n DESC, decision
            """,
            (target_date,),
        ).fetchall()


def candidate_hard_block_reason_rows(target_date: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT hard_block_reason, COUNT(*) AS n
            FROM auto_buy_candidates
            WHERE substr(timestamp, 1, 10) = ?
              AND hard_block_reason IS NOT NULL
              AND hard_block_reason != ''
            GROUP BY hard_block_reason
            ORDER BY n DESC, hard_block_reason
            LIMIT 10
            """,
            (target_date,),
        ).fetchall()


def top_candidate_rows(target_date: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT timestamp, symbol, signal_source, decision, score,
                   session_trend_label, session_trend_score,
                   setup_label, reason, order_submitted, order_id
            FROM auto_buy_candidates
            WHERE substr(timestamp, 1, 10) = ?
            ORDER BY score DESC, id DESC
            LIMIT 15
            """,
            (target_date,),
        ).fetchall()


def strategy_memory_hard_block_candidate_rows(
    target_date: str,
    *,
    symbol: str | None = None,
    db_path=DB_PATH,
) -> list[dict[str, Any]]:
    clauses = [
        "substr(timestamp, 1, 10) = ?",
        "hard_block_reason LIKE 'strategy_memory_avoid%'",
    ]
    params: list[Any] = [target_date]
    if symbol:
        clauses.append("UPPER(symbol) = ?")
        params.append(symbol.upper())

    with get_connection(db_path) as con:
        if not table_exists("auto_buy_candidates", db_path=db_path):
            return []
        rows = con.execute(
            f"""
            SELECT
                timestamp AS candidate_ts,
                symbol,
                'buy' AS action,
                'entry' AS candidate_kind,
                'scored_not_taken' AS candidate_status,
                score,
                decision,
                reason,
                setup_label,
                hard_block_reason,
                NULL AS candidate_json
            FROM auto_buy_candidates
            WHERE {" AND ".join(clauses)}
            ORDER BY score DESC, timestamp ASC, id ASC
            """,
            params,
        ).fetchall()
    return [dict(row) for row in rows]


def enrich_candidate_universe_json(
    rows: list[dict[str, Any]],
    *,
    db_path=DB_PATH,
) -> list[dict[str, Any]]:
    if not rows:
        return rows
    with get_connection(db_path) as con:
        if not table_exists("candidate_universe", db_path=db_path):
            return rows
        for row in rows:
            payload_row = con.execute(
                """
                SELECT candidate_json
                FROM candidate_universe
                WHERE symbol = ?
                  AND candidate_ts = ?
                LIMIT 1
                """,
                (row.get("symbol"), row.get("candidate_ts")),
            ).fetchone()
            if payload_row is not None:
                row["candidate_json"] = payload_row["candidate_json"]
    return rows


def signal_source_decision_rows(target_date: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT
                COALESCE(signal_source, 'unknown') AS signal_source,
                COALESCE(decision, 'unknown') AS decision,
                COUNT(*) AS n,
                SUM(CASE WHEN order_submitted = 1 THEN 1 ELSE 0 END) AS submitted,
                MAX(score) AS max_score
            FROM auto_buy_candidates
            WHERE substr(timestamp, 1, 10) = ?
            GROUP BY signal_source, decision
            ORDER BY signal_source, n DESC, decision
            """,
            (target_date,),
        ).fetchall()


def signal_source_readiness_summary(target_date: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT
                COUNT(*) AS rows,
                SUM(CASE WHEN signal_source = 'tradingview_alert' THEN 1 ELSE 0 END) AS legacy_tv_rows,
                SUM(CASE WHEN signal_source = 'internal_bar_only' THEN 1 ELSE 0 END) AS internal_rows,
                SUM(CASE WHEN signal_source = 'tradingview_alert'
                          AND decision = 'strong_buy_candidate' THEN 1 ELSE 0 END) AS legacy_tv_strong,
                SUM(CASE WHEN signal_source = 'tradingview_alert'
                          AND order_submitted = 1 THEN 1 ELSE 0 END) AS legacy_tv_submitted,
                SUM(CASE WHEN signal_source = 'internal_bar_only'
                          AND decision = 'strong_buy_candidate' THEN 1 ELSE 0 END) AS internal_strong,
                SUM(CASE WHEN signal_source = 'internal_bar_only'
                          AND order_submitted = 1 THEN 1 ELSE 0 END) AS internal_submitted
            FROM auto_buy_candidates
            WHERE substr(timestamp, 1, 10) = ?
            """,
            (target_date,),
        ).fetchone()


def live_block_reason_rows(target_date: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT
                COALESCE(signal_source, 'unknown') AS signal_source,
                COALESCE(live_block_reason, 'none') AS live_block_reason,
                COUNT(*) AS n
            FROM auto_buy_decision_snapshots
            WHERE substr(candidate_timestamp, 1, 10) = ?
              AND live_block_reason IS NOT NULL
              AND live_block_reason != ''
            GROUP BY signal_source, live_block_reason
            ORDER BY n DESC, signal_source, live_block_reason
            LIMIT 20
            """,
            (target_date,),
        ).fetchall()


def rolling_context_summary(target_date: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT
                COUNT(*) AS rows,
                SUM(
                    CASE
                        WHEN json_extract(candidate_json, '$.five_day_return_pct') IS NOT NULL
                          THEN 1 ELSE 0
                    END
                ) AS rows_with_5d,
                ROUND(AVG(json_extract(candidate_json, '$.five_day_return_pct')), 3)
                    AS avg_5d_return_pct,
                ROUND(MAX(json_extract(candidate_json, '$.five_day_return_pct')), 3)
                    AS max_5d_return_pct,
                ROUND(MIN(json_extract(candidate_json, '$.five_day_return_pct')), 3)
                    AS min_5d_return_pct,
                SUM(
                    CASE
                        WHEN json_extract(candidate_json, '$.rolling_momentum_source')
                             = 'rolling_momentum_json'
                          THEN 1 ELSE 0
                    END
                ) AS rolling_source_rows
            FROM auto_buy_decision_snapshots
            WHERE substr(candidate_timestamp, 1, 10) = ?
            """,
            (target_date,),
        ).fetchone()


def filled_trade_rows_for_intraday_feedback(target_date: str, db_path=DB_PATH):
    if not table_exists("trades", db_path=db_path):
        return []
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT
                id,
                timestamp,
                symbol,
                action,
                qty,
                fill_price,
                order_id,
                setup_label,
                setup_policy_action,
                ml_prediction_bucket,
                session_trend_label,
                session_return_pct,
                buy_opportunity_recommendation,
                confidence,
                rejection_reason
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND approved = 1
              AND order_status = 'filled'
              AND action IN ('buy', 'sell')
              AND qty IS NOT NULL
              AND qty > 0
              AND fill_price IS NOT NULL
              AND fill_price > 0
            ORDER BY timestamp ASC, id ASC
            """,
            (target_date,),
        ).fetchall()


def historical_matched_trade_rows_for_feedback(
    target_date: str,
    *,
    lookback_days: int = 20,
    db_path=DB_PATH,
):
    if not table_exists("matched_trades", db_path=db_path):
        return []

    columns = table_columns("matched_trades", db_path=db_path)
    required = {
        "symbol",
        "entry_timestamp",
        "exit_timestamp",
        "holding_minutes",
        "qty",
        "entry_price",
        "exit_price",
        "realized_pnl_pct",
        "won",
    }
    if not required.issubset(columns):
        return []

    optional = {
        "setup_policy_action": "setup_policy_action",
        "setup_label": "setup_label",
        "ml_prediction_bucket": "ml_prediction_bucket",
        "session_trend_label": "session_trend_label",
        "buy_opportunity_recommendation": "buy_opportunity_recommendation",
        "entry_source": "entry_source",
        "signal_source": "signal_source",
    }
    select_cols = [
        "id",
        "symbol",
        "entry_timestamp",
        "exit_timestamp",
        "holding_minutes",
        "qty",
        "entry_price",
        "exit_price",
        "realized_pnl_pct",
        "won",
    ]
    for name in optional:
        if name in columns:
            select_cols.append(name)
        else:
            select_cols.append(f"NULL AS {optional[name]}")

    source_filter = ""
    if "entry_source" in columns or "signal_source" in columns:
        source_terms = []
        if "entry_source" in columns:
            source_terms.append("entry_source = 'auto_buy_manager'")
        if "signal_source" in columns:
            source_terms.append(
                "signal_source IN ('auto_buy_manager', 'internal_bar_only', 'tradingview_alert')"
            )
        source_filter = f" AND ({' OR '.join(source_terms)})"

    with get_connection(db_path) as con:
        return con.execute(
            f"""
            SELECT {", ".join(select_cols)}
            FROM matched_trades
            WHERE substr(entry_timestamp, 1, 10) < ?
              AND date(substr(entry_timestamp, 1, 10)) >= date(?, ?)
              AND realized_pnl_pct IS NOT NULL
              {source_filter}
            ORDER BY entry_timestamp ASC, id ASC
            """,
            (target_date, target_date, f"-{int(lookback_days)} days"),
        ).fetchall()


def replace_historical_outcome_feedback(
    *,
    created_at: str,
    target_date: str,
    lookback_days: int,
    evidence_rows: list[dict[str, Any]],
    db_path=DB_PATH,
) -> int:
    init_tables(db_path=db_path)
    with get_connection(db_path) as con:
        con.execute(
            """
            DELETE FROM auto_buy_historical_outcome_feedback
            WHERE target_date = ? AND lookback_days = ?
            """,
            (target_date, int(lookback_days)),
        )
        for row in evidence_rows:
            con.execute(
                """
                INSERT INTO auto_buy_historical_outcome_feedback (
                    created_at,
                    target_date,
                    lookback_days,
                    feedback_key,
                    status,
                    trades,
                    wins,
                    losses,
                    loss_rate,
                    avg_pnl_pct,
                    min_pnl_pct,
                    max_pnl_pct,
                    symbols_json,
                    sources_json,
                    evidence_json,
                    runtime_effect
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    created_at,
                    target_date,
                    int(lookback_days),
                    row.get("key"),
                    row.get("status"),
                    row.get("trades"),
                    row.get("wins"),
                    row.get("losses"),
                    row.get("loss_rate"),
                    row.get("avg_pnl_pct"),
                    row.get("min_pnl_pct"),
                    row.get("max_pnl_pct"),
                    json.dumps(row.get("symbols") or [], sort_keys=True),
                    json.dumps(row.get("sources") or [], sort_keys=True),
                    json.dumps(row, sort_keys=True),
                    row.get("runtime_effect") or "paper_historical_outcome_feedback_materialized",
                ),
            )
    return len(evidence_rows)


def historical_outcome_feedback_rows(
    target_date: str,
    *,
    lookback_days: int,
    db_path=DB_PATH,
):
    if not table_exists("auto_buy_historical_outcome_feedback", db_path=db_path):
        return []
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT *
            FROM auto_buy_historical_outcome_feedback
            WHERE target_date = ?
              AND lookback_days = ?
            ORDER BY trades DESC, feedback_key
            """,
            (target_date, int(lookback_days)),
        ).fetchall()


def insert_intraday_feedback_event(
    *,
    created_at: str,
    target_date: str,
    symbol: str | None,
    feedback_key: str,
    status: str,
    score_penalty: float | None,
    hard_block_reason: str | None,
    evidence_json: str,
    candidate_json: str,
    runtime_effect: str,
    db_path=DB_PATH,
) -> None:
    with get_connection(db_path) as con:
        con.execute(
            """
            INSERT INTO auto_buy_intraday_feedback (
                created_at,
                target_date,
                symbol,
                feedback_key,
                status,
                score_penalty,
                hard_block_reason,
                evidence_json,
                candidate_json,
                runtime_effect
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                target_date,
                symbol,
                feedback_key,
                status,
                score_penalty,
                hard_block_reason,
                evidence_json,
                candidate_json,
                runtime_effect,
            ),
        )


def intraday_feedback_summary(target_date: str, db_path=DB_PATH):
    if not table_exists("auto_buy_intraday_feedback", db_path=db_path):
        return []
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT
                status,
                feedback_key,
                COUNT(*) AS n,
                MAX(score_penalty) AS max_penalty,
                MAX(hard_block_reason) AS hard_block_reason,
                MAX(COALESCE(json_extract(evidence_json, '$.same_day_trades'), 0))
                    AS same_day_trades,
                MAX(COALESCE(json_extract(evidence_json, '$.historical_trades'), 0))
                    AS historical_trades,
                MAX(COALESCE(json_extract(evidence_json, '$.sources'), '[]'))
                    AS evidence_sources
            FROM auto_buy_intraday_feedback
            WHERE target_date = ?
            GROUP BY status, feedback_key
            ORDER BY n DESC, status, feedback_key
            LIMIT 12
            """,
            (target_date,),
        ).fetchall()


def decision_snapshot_rows_between(
    start_date: str,
    end_date: str,
    *,
    symbol: str | None = None,
    db_path=DB_PATH,
):
    clauses = ["substr(candidate_timestamp, 1, 10) BETWEEN ? AND ?"]
    params: list[Any] = [start_date, end_date]
    if symbol:
        clauses.append("UPPER(symbol) = ?")
        params.append(symbol.upper())
    with get_connection(db_path) as con:
        return con.execute(
            f"""
            SELECT *
            FROM auto_buy_decision_snapshots
            WHERE {" AND ".join(clauses)}
            ORDER BY candidate_timestamp ASC, id ASC
            """,
            params,
        ).fetchall()


def tradingview_webhook_trade_count(target_date: str, symbols: list[str], db_path=DB_PATH) -> int:
    if not symbols:
        return 0
    if not table_exists("trades", db_path=db_path):
        return 0
    placeholders = ",".join("?" for _ in symbols)
    with get_connection(db_path) as con:
        row = con.execute(
            f"""
            SELECT COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND symbol IN ({placeholders})
              AND action IN ('buy', 'sell')
            """,
            [target_date, *symbols],
        ).fetchone()
    return int(row["n"] or 0) if row else 0


def decision_snapshot_summary(target_date: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT COUNT(*) AS n,
                   SUM(CASE WHEN order_submitted = 1 THEN 1 ELSE 0 END) AS submitted,
                   SUM(CASE WHEN live_block_reason IS NOT NULL AND live_block_reason != '' THEN 1 ELSE 0 END) AS blocked
            FROM auto_buy_decision_snapshots
            WHERE substr(candidate_timestamp, 1, 10) = ?
            """,
            (target_date,),
        ).fetchone()


def latest_session(symbol: str, db_path=DB_PATH) -> dict[str, Any]:
    with get_connection(db_path) as con:
        row = con.execute(
            "SELECT * FROM session_momentum WHERE symbol = ?",
            (symbol,),
        ).fetchone()
    return dict(row) if row else {}


def latest_feature(symbol: str, db_path=DB_PATH) -> dict[str, Any]:
    with get_connection(db_path) as con:
        row = con.execute(
            """
            SELECT *
            FROM feature_snapshots
            WHERE symbol = ?
            ORDER BY id DESC
            LIMIT 1
            """,
            (symbol,),
        ).fetchone()
    return dict(row) if row else {}


def auto_buy_orders_today(today: str, db_path=DB_PATH) -> int:
    with get_connection(db_path) as con:
        row = con.execute(
            """
            SELECT COUNT(*) AS n
            FROM auto_buy_candidates
            WHERE substr(timestamp, 1, 10) = ?
              AND order_submitted = 1
            """,
            (today,),
        ).fetchone()
    return int(row["n"] or 0) if row else 0


def latest_auto_buy_order(symbol: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT timestamp, order_id
            FROM auto_buy_candidates
            WHERE symbol = ?
              AND order_submitted = 1
            ORDER BY timestamp DESC, id DESC
            LIMIT 1
            """,
            (symbol.upper(),),
        ).fetchone()


def app_buy_cooldown(symbol: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT last_order_time
            FROM cooldowns
            WHERE symbol = ?
              AND action = 'buy'
            """,
            (symbol.upper(),),
        ).fetchone()


def recent_sell(symbol: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT last_sell_time, last_sell_price
            FROM recent_sells
            WHERE symbol = ?
            """,
            (symbol.upper(),),
        ).fetchone()


def app_approved_buys_today(today: str, symbol: str, db_path=DB_PATH) -> int:
    with get_connection(db_path) as con:
        row = con.execute(
            """
            SELECT COUNT(*) AS n
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND symbol = ?
              AND action = 'buy'
              AND approved = 1
              AND order_id IS NOT NULL
            """,
            (today, symbol.upper()),
        ).fetchone()
    return int(row["n"] or 0) if row else 0


def strong_buy_signals_today(symbol: str, today: str, db_path=DB_PATH) -> int:
    with get_connection(db_path) as con:
        row = con.execute(
            """
            SELECT COUNT(*) AS n
            FROM auto_buy_candidates
            WHERE symbol = ?
              AND substr(timestamp, 1, 10) = ?
              AND decision = 'strong_buy_candidate'
              AND order_submitted = 1
            """,
            (symbol.upper(), today),
        ).fetchone()
    return int(row["n"] or 0) if row else 0


def write_app_buy_cooldown(symbol: str, timestamp: str, db_path=DB_PATH) -> None:
    with get_connection(db_path) as con:
        con.execute(
            """
            INSERT OR REPLACE INTO cooldowns (symbol, action, last_order_time)
            VALUES (?, 'buy', ?)
            """,
            (symbol.upper(), timestamp),
        )


def insert_candidate_and_snapshot(
    *,
    timestamp: str,
    created_at: str,
    candidate: dict[str, Any],
    live_buy_enabled: bool,
    order: dict[str, Any],
    candidate_json: str,
    order_json: str,
    db_path=DB_PATH,
) -> None:
    with get_connection(db_path) as con:
        con.execute(
            """
            INSERT INTO auto_buy_candidates (
                timestamp, symbol, signal_source, decision, score, reason,
                market_bias, entry_quality, risk_level,
                session_trend_label, session_trend_score, session_return_pct,
                momentum_5m_pct, momentum_15m_pct, momentum_30m_pct,
                distance_from_vwap_pct,
                setup_label, setup_recommendation, setup_score,
                hard_block_reason,
                feature_snapshot_id, live_buy_enabled, order_submitted, order_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                candidate.get("symbol"),
                candidate.get("signal_source"),
                candidate.get("decision"),
                candidate.get("score"),
                candidate.get("reason"),
                candidate.get("market_bias"),
                candidate.get("entry_quality"),
                candidate.get("risk_level"),
                candidate.get("session_trend_label"),
                candidate.get("session_trend_score"),
                candidate.get("session_return_pct"),
                candidate.get("momentum_5m_pct"),
                candidate.get("momentum_15m_pct"),
                candidate.get("momentum_30m_pct"),
                candidate.get("distance_from_vwap_pct"),
                candidate.get("setup_label"),
                candidate.get("setup_recommendation"),
                candidate.get("setup_score"),
                candidate.get("hard_block_reason"),
                candidate.get("feature_snapshot_id"),
                1 if live_buy_enabled else 0,
                1 if order else 0,
                order.get("order_id") if isinstance(order, dict) else None,
            ),
        )
        con.execute(
            """
            INSERT INTO auto_buy_decision_snapshots (
                created_at, candidate_timestamp, symbol, signal_source,
                decision, score, reason, hard_block_reason, live_buy_enabled,
                live_block_reason, risk_cross_check_reason, order_submitted,
                order_id, order_status, candidate_json, order_json, execution_status
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                created_at,
                timestamp,
                candidate.get("symbol"),
                candidate.get("signal_source"),
                candidate.get("decision"),
                candidate.get("score"),
                candidate.get("reason"),
                candidate.get("hard_block_reason"),
                1 if live_buy_enabled else 0,
                candidate.get("live_block_reason"),
                candidate.get("risk_cross_check_reason"),
                1 if order else 0,
                order.get("order_id") if isinstance(order, dict) else None,
                order.get("status") if isinstance(order, dict) else None,
                candidate_json,
                order_json,
                "ROUTED" if order else "PENDING",
            ),
        )


def trade_order_exists(order_id: str, db_path=DB_PATH) -> bool:
    with get_connection(db_path) as con:
        row = con.execute(
            "SELECT id FROM trades WHERE order_id = ? LIMIT 1",
            (order_id,),
        ).fetchone()
    return bool(row)


def insert_auto_buy_trade(
    *,
    timestamp: str,
    candidate: dict[str, Any],
    order: dict[str, Any],
    qty: int | None,
    position_size_pct: float,
    stop_loss_pct: float,
    take_profit_pct: float,
    db_path=DB_PATH,
) -> None:
    with get_connection(db_path) as con:
        con.execute(
            """
            INSERT INTO trades (
                timestamp,
                symbol,
                action,
                signal_price,
                approved,
                rejection_reason,
                confidence,
                position_size_pct,
                stop_loss_pct,
                take_profit_pct,
                order_id,
                order_status,
                qty,
                fill_price,
                market_bias,
                risk_level,
                entry_quality,
                session_trend_label,
                session_trend_score,
                session_return_pct,
                session_momentum_5m_pct,
                session_momentum_15m_pct,
                session_momentum_30m_pct,
                session_distance_from_vwap_pct,
                setup_label,
                setup_policy_action,
                setup_policy_reason,
                prediction_score,
                prediction_decision,
                prediction_reason,
                ml_prediction_score,
                ml_prediction_bucket,
                buy_opportunity_score,
                buy_opportunity_recommendation,
                buy_opportunity_reason,
                session_momentum_severity,
                effective_size_cap_pct,
                dominant_limiter
            ) VALUES (?, ?, 'buy', ?, 1, ?, ?, ?, ?, ?, ?, ?, ?, NULL,
                      ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                timestamp,
                candidate.get("symbol"),
                order.get("current_price"),
                "auto_buy_manager: internal bar-derived buy submitted",
                "auto_buy_manager",
                position_size_pct,
                stop_loss_pct,
                take_profit_pct,
                order.get("order_id"),
                order.get("status") or "submitted",
                qty,
                candidate.get("market_bias"),
                candidate.get("risk_level"),
                candidate.get("entry_quality"),
                candidate.get("session_trend_label"),
                candidate.get("session_trend_score"),
                candidate.get("session_return_pct"),
                candidate.get("momentum_5m_pct"),
                candidate.get("momentum_15m_pct"),
                candidate.get("momentum_30m_pct"),
                candidate.get("distance_from_vwap_pct"),
                candidate.get("setup_label"),
                candidate.get("setup_recommendation"),
                candidate.get("reason"),
                candidate.get("prediction_score"),
                candidate.get("prediction_decision"),
                candidate.get("prediction_reason"),
                candidate.get("ml_prediction_score"),
                candidate.get("ml_prediction_bucket"),
                candidate.get("score"),
                candidate.get("decision"),
                candidate.get("reason"),
                candidate.get("session_momentum_severity"),
                candidate.get("effective_size_cap_pct"),
                candidate.get("dominant_limiter"),
            ),
        )
