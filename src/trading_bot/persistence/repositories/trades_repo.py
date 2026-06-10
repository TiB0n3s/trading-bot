"""Repository for trades table reads and writes."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import pytz
from db import DB_PATH, get_connection
from repositories.trade_accounting import fill_bearing_order_condition


def insert_trade_row(columns: list[str], values: list[Any], db_path=DB_PATH) -> int:
    placeholders = ", ".join(["?"] * len(values))
    col_sql = ", ".join(columns)
    with get_connection(db_path) as con:
        cur = con.execute(f"INSERT INTO trades ({col_sql}) VALUES ({placeholders})", values)
        return int(cur.lastrowid)


def successful_buys_today(symbol: str, db_path=DB_PATH) -> int:
    today = datetime.now(pytz.timezone("America/New_York")).strftime("%Y-%m-%d")
    with get_connection(db_path) as con:
        row = con.execute(
            """
            SELECT COUNT(*)
            FROM trades
            WHERE symbol = ?
              AND LOWER(action) = 'buy'
              AND approved = 1
              AND order_id IS NOT NULL
              AND timestamp LIKE ?
            """,
            (symbol, f"{today}%"),
        ).fetchone()
    return int(row[0] or 0)


def filled_buys_today(symbol: str, db_path=DB_PATH) -> int:
    today = datetime.now(pytz.timezone("America/New_York")).strftime("%Y-%m-%d")
    fill_bearing = fill_bearing_order_condition()
    with get_connection(db_path) as con:
        row = con.execute(
            f"""
            SELECT COUNT(*)
            FROM trades
            WHERE symbol = ?
              AND LOWER(action) = 'buy'
              AND approved = 1
              AND order_id IS NOT NULL
              AND {fill_bearing}
              AND timestamp LIKE ?
            """,
            (symbol, f"{today}%"),
        ).fetchone()
    return int(row[0] or 0)


def cash_safe_buys_today(symbol: str, db_path=DB_PATH) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    with get_connection(db_path) as con:
        row = con.execute(
            """
            SELECT COUNT(*) FROM trades
            WHERE timestamp LIKE ?
              AND symbol = ?
              AND action = 'buy'
              AND approved = 1
              AND order_id IS NOT NULL
            """,
            (f"{today}%", symbol),
        ).fetchone()
    return int(row[0] or 0)


def has_open_position(symbol: str, db_path=DB_PATH) -> bool:
    fill_bearing = fill_bearing_order_condition()
    with get_connection(db_path) as con:
        table_exists = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = 'trades'"
        ).fetchone()
        if table_exists is None:
            return False
        row = con.execute(
            f"""
            SELECT SUM(CASE WHEN LOWER(action)='buy'  THEN COALESCE(qty, 0)
                           WHEN LOWER(action)='sell' THEN -COALESCE(qty, 0)
                           ELSE 0 END) AS net_qty
            FROM trades
            WHERE symbol = ?
              AND order_id IS NOT NULL
              AND {fill_bearing}
            """,
            (symbol,),
        ).fetchone()
    return int(row["net_qty"] or 0) > 0


def recent_signal_history(approved_symbols: list[str], db_path=DB_PATH):
    if not approved_symbols:
        return []
    placeholders = ",".join("?" for _ in approved_symbols)
    with get_connection(db_path) as con:
        return con.execute(
            f"""
            SELECT symbol, action, timestamp FROM (
                SELECT symbol, action, timestamp,
                       ROW_NUMBER() OVER (PARTITION BY symbol ORDER BY timestamp DESC) AS rn
                FROM trades
                WHERE symbol IS NOT NULL
                  AND action IS NOT NULL
                  AND symbol IN ({placeholders})
            ) WHERE rn <= 10
            ORDER BY symbol, timestamp DESC
            """,
            approved_symbols,
        ).fetchall()


def recent_actions_for_trend(symbol: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            "SELECT action FROM trades "
            "WHERE symbol = ? AND action IS NOT NULL "
            "AND (approved = 1 "
            "OR rejection_reason LIKE 'confidence_gate:%' "
            "OR rejection_reason LIKE 'trend_gate:%' "
            "OR rejection_reason LIKE 'trend_confirmation:%') "
            "ORDER BY timestamp DESC LIMIT 10",
            (symbol,),
        ).fetchall()


def open_entry_rows(symbol: str, db_path=DB_PATH):
    fill_bearing = fill_bearing_order_condition()
    with get_connection(db_path) as con:
        return con.execute(
            f"""
            SELECT id, timestamp, symbol, action, qty, fill_price, signal_price,
                   order_status, order_id,
                   market_bias, risk_level, entry_quality,
                   trend_direction, trend_strength,
                   momentum_direction, momentum_pct,
                   macro_regime, risk_multiplier,
                   correlation_cluster, cluster_exposure_pct
            FROM trades
            WHERE symbol = ?
              AND order_id IS NOT NULL
              AND {fill_bearing}
              AND LOWER(action) IN ('buy', 'sell')
              AND qty IS NOT NULL
            ORDER BY timestamp ASC, id ASC
            """,
            (symbol,),
        ).fetchall()


def portfolio_rotation_count_today(db_path=DB_PATH) -> int:
    today = datetime.now(pytz.timezone("America/New_York")).strftime("%Y-%m-%d")
    with get_connection(db_path) as con:
        row = con.execute(
            """
            SELECT COUNT(*)
            FROM trades
            WHERE timestamp LIKE ?
              AND approved = 1
              AND LOWER(action) = 'sell'
              AND confidence = 'rotation'
            """,
            (f"{today}%",),
        ).fetchone()
    return int(row[0] or 0)


def second_look_blocks_today(symbol: str, db_path=DB_PATH) -> int:
    today = datetime.now().strftime("%Y-%m-%d")
    with get_connection(db_path) as con:
        row = con.execute(
            """
            SELECT COUNT(*) AS cnt
            FROM trades
            WHERE timestamp LIKE ?
              AND symbol = ?
              AND action = 'buy'
              AND approved = 0
              AND rejection_reason LIKE 'second_look:%'
            """,
            (f"{today}%", symbol),
        ).fetchone()
    return int(row["cnt"] or 0) if row else 0


def today_signal_counts(db_path=DB_PATH) -> dict[str, int]:
    today = datetime.now().strftime("%Y-%m-%d")
    with get_connection(db_path) as con:
        row = con.execute(
            """
            SELECT
                COUNT(*)                                          AS total,
                SUM(approved)                                     AS approved,
                SUM(1 - approved)                                 AS rejected,
                SUM(CASE WHEN order_id IS NOT NULL THEN 1 END)    AS orders_placed,
                SUM(CASE WHEN approved=1 AND order_id IS NULL
                         THEN 1 END)                              AS null_orders
            FROM trades WHERE timestamp LIKE ?
            """,
            (f"{today}%",),
        ).fetchone()
    return {
        "total": row[0] or 0,
        "approved": row[1] or 0,
        "rejected": row[2] or 0,
        "orders_placed": row[3] or 0,
        "null_orders": row[4] or 0,
    }


def weekly_symbol_performance(symbol: str, db_path=DB_PATH) -> dict[str, Any]:
    with get_connection(db_path) as con:
        row = con.execute(
            """
            SELECT
                COUNT(*) AS trades,
                SUM(CASE WHEN realized_pnl > 0 THEN 1 ELSE 0 END) AS wins,
                SUM(CASE WHEN realized_pnl < 0 THEN 1 ELSE 0 END) AS losses,
                SUM(COALESCE(realized_pnl, 0)) AS pnl,
                AVG(realized_pnl) AS expectancy,
                AVG(realized_pnl_pct) AS avg_pnl_pct
            FROM matched_trades
            WHERE symbol = ?
              AND entry_timestamp >= date('now','weekday 1','-7 days')
            """,
            (symbol,),
        ).fetchone()

    trades = int(row["trades"] or 0) if row else 0
    wins = int(row["wins"] or 0) if row else 0
    losses = int(row["losses"] or 0) if row else 0
    pnl = float(row["pnl"] or 0.0) if row else 0.0
    expectancy = float(row["expectancy"] or 0.0) if row else 0.0
    avg_pnl_pct = float(row["avg_pnl_pct"] or 0.0) if row else 0.0
    win_rate = wins / trades if trades else 0.0

    label = "neutral"
    if trades >= 3 and expectancy > 0 and win_rate >= 0.75:
        label = "strong_weekly_boost"
    elif trades >= 2 and expectancy > 0 and win_rate >= 0.50:
        label = "weekly_boost"
    elif trades >= 2 and (expectancy < 0 or win_rate < 0.35):
        label = "weekly_penalty"

    return {
        "label": label,
        "trades": trades,
        "wins": wins,
        "losses": losses,
        "win_rate": round(win_rate, 4),
        "pnl": round(pnl, 2),
        "expectancy": round(expectancy, 2),
        "avg_pnl_pct": round(avg_pnl_pct, 4),
    }


def recent_symbol_outcomes(symbol: str, limit: int = 10, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT won, realized_pnl_pct, holding_minutes,
                   trend_direction, trend_strength
            FROM matched_trades
            WHERE symbol = ?
            ORDER BY exit_timestamp DESC
            LIMIT ?
            """,
            (symbol, int(limit)),
        ).fetchall()


def buy_opportunity_report_rows(target_date: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT timestamp, symbol, approved, rejection_reason,
                   buy_opportunity_score,
                   buy_opportunity_recommendation,
                   buy_opportunity_reason,
                   market_bias, risk_level, entry_quality,
                   trend_direction, trend_strength,
                   setup_label, setup_policy_action,
                   prediction_score, prediction_decision
            FROM trades
            WHERE timestamp LIKE ?
              AND action = 'buy'
            ORDER BY timestamp ASC
            """,
            (f"{target_date}%",),
        ).fetchall()


def adaptive_impact_report_rows(target_date: str, db_path=DB_PATH):
    with get_connection(db_path) as con:
        return con.execute(
            """
            SELECT
                timestamp,
                symbol,
                action,
                approved,
                rejection_reason,
                market_bias,
                risk_level,
                entry_quality,
                trend_direction,
                trend_strength,
                setup_label,
                setup_policy_action,
                prediction_score,
                prediction_decision
            FROM trades
            WHERE timestamp LIKE ?
              AND action = 'buy'
            ORDER BY timestamp ASC
            """,
            (f"{target_date}%",),
        ).fetchall()


def tradingview_alert_rows(report_date: str, symbols: list[str], db_path=DB_PATH):
    if not symbols:
        return []

    placeholders = ",".join("?" for _ in symbols)
    with get_connection(db_path) as con:
        return con.execute(
            f"""
            SELECT symbol, timestamp, action, approved, rejection_reason
            FROM trades
            WHERE substr(timestamp, 1, 10) = ?
              AND symbol IN ({placeholders})
            ORDER BY symbol, timestamp
            """,
            [report_date, *symbols],
        ).fetchall()
