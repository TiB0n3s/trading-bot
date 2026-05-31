"""Repository boundary for matched-trade rebuilds."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class TradeMatcherRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def load_filled_trades(self) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT *
                FROM trades
                WHERE approved = 1
                  AND action IN ('buy', 'sell')
                  AND qty IS NOT NULL
                  AND fill_price IS NOT NULL
                  AND order_status IN ('filled', 'partially_filled')
                ORDER BY timestamp ASC, id ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def load_position_manager_sells(self) -> list[dict[str, Any]]:
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT *
                FROM trades
                WHERE action = 'sell'
                  AND approved = 1
                  AND order_status = 'filled'
                  AND fill_price IS NOT NULL
                  AND rejection_reason LIKE 'position_manager_%'
                ORDER BY timestamp ASC
                """
            ).fetchall()
        return [dict(row) for row in rows]

    def existing_synthetic_order_ids(self) -> set[str]:
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT exit_order_id
                FROM matched_trades
                WHERE match_source = 'synthetic_position_manager_exit'
                  AND exit_order_id IS NOT NULL
                """
            ).fetchall()
        return {str(row["exit_order_id"] or "") for row in rows}

    def drawdown_matched_rows(self, target_date: str) -> list[Any]:
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT symbol, qty, entry_price, exit_price, realized_pnl, realized_pnl_pct,
                       entry_timestamp, exit_timestamp, trend_direction, trend_strength,
                       market_bias, risk_level, entry_quality
                FROM matched_trades
                WHERE exit_timestamp LIKE ?
                ORDER BY realized_pnl ASC
                """,
                (f"{target_date}%",),
            ).fetchall()

    def event_payload_for_order(self, order_id: str | None) -> dict[str, Any] | None:
        if not order_id:
            return None

        try:
            with get_connection(self.db_path) as con:
                rows = con.execute(
                    """
                    SELECT payload_json
                    FROM bot_events
                    WHERE event_type = 'POSITION_MANAGER_ORDER'
                      AND payload_json LIKE ?
                    ORDER BY id DESC
                    LIMIT 1
                    """,
                    (f"%{order_id}%",),
                ).fetchall()
        except Exception:
            return None

        if not rows:
            return None

        try:
            return json.loads(rows[0]["payload_json"] or "{}")
        except Exception:
            return None

    def init_matched_trades_table(self) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS matched_trades (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    symbol TEXT,
                    entry_timestamp TEXT,
                    exit_timestamp TEXT,
                    holding_minutes REAL,
                    qty REAL,
                    entry_price REAL,
                    exit_price REAL,
                    realized_pnl REAL,
                    realized_pnl_pct REAL,
                    won INTEGER,

                    macro_regime TEXT,
                    risk_multiplier REAL,
                    market_bias TEXT,
                    risk_level TEXT,
                    entry_quality TEXT,
                    trend_direction TEXT,
                    trend_strength TEXT,
                    momentum_direction TEXT,
                    momentum_pct REAL,
                    correlation_cluster TEXT,
                    cluster_exposure_pct REAL,

                    market_bias_effective TEXT,
                    market_bias_override_reason TEXT,
                    fundamental_score TEXT,

                    session_trend_label TEXT,
                    session_trend_score REAL,
                    session_return_pct REAL,
                    session_momentum_5m_pct REAL,
                    session_momentum_15m_pct REAL,
                    session_momentum_30m_pct REAL,
                    session_distance_from_vwap_pct REAL,
                    session_momentum_reason TEXT,

                    prediction_score REAL,
                    prediction_decision TEXT,
                    prediction_reason TEXT,

                    setup_label TEXT,
                    setup_policy_action TEXT,
                    setup_policy_reason TEXT,
                    setup_confidence_adjustment REAL,
                    setup_size_multiplier REAL,
                    setup_unknown_reason TEXT,
                    ml_prediction_score REAL,
                    ml_prediction_bucket TEXT,

                    buy_opportunity_score REAL,
                    buy_opportunity_recommendation TEXT,
                    buy_opportunity_reason TEXT,
                    exit_reason TEXT,
                    exit_order_id TEXT,
                    entry_source TEXT,
                    signal_source TEXT,
                    match_source TEXT,
                    mfe_pct REAL,
                    capture_ratio REAL
                )
                """
            )

            existing = {
                row["name"]
                for row in con.execute("PRAGMA table_info(matched_trades)").fetchall()
            }

            add_columns = {
                "market_bias_effective": "TEXT",
                "market_bias_override_reason": "TEXT",
                "fundamental_score": "TEXT",
                "session_trend_label": "TEXT",
                "session_trend_score": "REAL",
                "session_return_pct": "REAL",
                "session_momentum_5m_pct": "REAL",
                "session_momentum_15m_pct": "REAL",
                "session_momentum_30m_pct": "REAL",
                "session_distance_from_vwap_pct": "REAL",
                "session_momentum_reason": "TEXT",
                "prediction_score": "REAL",
                "prediction_decision": "TEXT",
                "prediction_reason": "TEXT",
                "setup_label": "TEXT",
                "setup_policy_action": "TEXT",
                "setup_policy_reason": "TEXT",
                "setup_confidence_adjustment": "REAL",
                "setup_size_multiplier": "REAL",
                "setup_unknown_reason": "TEXT",
                "ml_prediction_score": "REAL",
                "ml_prediction_bucket": "TEXT",
                "buy_opportunity_score": "REAL",
                "buy_opportunity_recommendation": "TEXT",
                "buy_opportunity_reason": "TEXT",
                "signal_source": "TEXT",
                "mfe_pct": "REAL",
                "capture_ratio": "REAL",
            }

            for name, typ in add_columns.items():
                if name not in existing:
                    con.execute(f"ALTER TABLE matched_trades ADD COLUMN {name} {typ}")

    def replace_matched_trades(
        self,
        matched: list[dict[str, Any]],
        columns: list[str],
    ) -> None:
        placeholders = ", ".join(["?"] * len(columns))
        col_sql = ", ".join(columns)

        with get_connection(self.db_path) as con:
            con.execute("DELETE FROM matched_trades")
            for trade in matched:
                con.execute(
                    f"INSERT INTO matched_trades ({col_sql}) VALUES ({placeholders})",
                    [trade.get(column) for column in columns],
                )

            con.execute(
                """
                UPDATE matched_trades
                SET mfe_pct = (
                    SELECT MAX(pmc.unrealized_plpc)
                    FROM position_momentum_checks pmc
                    WHERE pmc.symbol = matched_trades.symbol
                      AND pmc.timestamp >= matched_trades.entry_timestamp
                      AND pmc.timestamp <= matched_trades.exit_timestamp
                )
                WHERE entry_timestamp IS NOT NULL
                  AND exit_timestamp IS NOT NULL
                """
            )
            con.execute(
                """
                UPDATE matched_trades
                SET capture_ratio = CASE
                    WHEN mfe_pct IS NOT NULL AND mfe_pct > 0
                        THEN ROUND(realized_pnl_pct / mfe_pct, 3)
                    ELSE NULL
                END
                """
            )
