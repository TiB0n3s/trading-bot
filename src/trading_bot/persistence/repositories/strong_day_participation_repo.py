"""Repository boundary for strong-day participation analytics."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path
from typing import Any

import pytz
from db import DB_PATH, get_connection

ET = pytz.timezone("America/New_York")


class StrongDayParticipationRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def init_table(self) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS strong_day_participation (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    market_date TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    signal_source TEXT,
                    min_session_pct REAL NOT NULL,
                    session_return_pct REAL,
                    mfe_pct REAL,
                    return_30m_pct REAL,
                    return_60m_pct REAL,
                    first_strong_time TEXT,
                    session_high_time TEXT,
                    primary_status TEXT,
                    primary_blocker TEXT,
                    buy_signal_count INTEGER,
                    approved_buy_count INTEGER,
                    rejected_buy_count INTEGER,
                    sell_signal_count INTEGER,
                    auto_buy_candidate_count INTEGER,
                    auto_buy_strong_count INTEGER,
                    auto_buy_watch_count INTEGER,
                    auto_buy_submitted_count INTEGER,
                    auto_buy_max_score REAL,
                    auto_buy_first_candidate_time TEXT,
                    auto_buy_first_strong_time TEXT,
                    prediction_score REAL,
                    prediction_decision TEXT,
                    prediction_confidence TEXT,
                    prediction_sample_size INTEGER,
                    prediction_timing_score REAL,
                    prediction_trend_score REAL,
                    prediction_trend_label TEXT,
                    raw_json TEXT,
                    generated_at TEXT NOT NULL,
                    UNIQUE(market_date, symbol, min_session_pct)
                )
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_strong_day_participation_date_symbol
                ON strong_day_participation(market_date, symbol)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_strong_day_participation_status
                ON strong_day_participation(market_date, primary_status)
                """
            )

    def symbol_trades(self, target_date: str, symbol: str) -> list[Any]:
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT id, timestamp, action, approved, rejection_reason,
                       signal_price, setup_label, setup_policy_action,
                       session_trend_label, session_trend_score,
                       buy_opportunity_score, buy_opportunity_recommendation,
                       momentum_pct, prediction_score, prediction_decision
                FROM trades
                WHERE timestamp LIKE ?
                  AND symbol = ?
                ORDER BY id ASC
                """,
                (f"{target_date}%", symbol.upper()),
            ).fetchall()

    def max_setup_score(self, target_date: str, symbol: str) -> float | None:
        try:
            with get_connection(self.db_path) as con:
                row = con.execute(
                    """
                    SELECT MAX(setup_score) AS v
                    FROM feature_snapshots
                    WHERE substr(timestamp, 1, 10) = ?
                      AND symbol = ?
                    """,
                    (target_date, symbol.upper()),
                ).fetchone()
            return float(row["v"]) if row and row["v"] is not None else None
        except Exception:
            return None

    def auto_buy_candidates(self, target_date: str, symbol: str) -> list[Any]:
        try:
            with get_connection(self.db_path) as con:
                return con.execute(
                    """
                    SELECT timestamp, decision, score, reason, hard_block_reason,
                           order_submitted, order_id
                    FROM auto_buy_candidates
                    WHERE substr(timestamp, 1, 10) = ?
                      AND symbol = ?
                    ORDER BY timestamp ASC, id ASC
                    """,
                    (target_date, symbol.upper()),
                ).fetchall()
        except Exception:
            return []

    def prediction(self, target_date: str, symbol: str) -> dict[str, Any]:
        try:
            with get_connection(self.db_path) as con:
                row = con.execute(
                    """
                    SELECT prediction_score, confidence, sample_size,
                           timing_score, trend_score, trend_label
                    FROM daily_symbol_predictions
                    WHERE market_date = ?
                      AND symbol = ?
                    """,
                    (target_date, symbol.upper()),
                ).fetchone()
            if not row:
                return {}
            prediction = dict(row)
            prediction["prediction_decision"] = None
            return prediction
        except Exception:
            return {}

    def upsert_results(
        self,
        results: list[dict[str, Any]],
        target_date: str,
        min_session_pct: float,
    ) -> int:
        self.init_table()
        generated_at = datetime.now(ET).isoformat()
        rows_written = 0
        with get_connection(self.db_path) as con:
            for result in results:
                if result.get("error"):
                    continue
                con.execute(
                    """
                    INSERT INTO strong_day_participation (
                        market_date, symbol, signal_source, min_session_pct,
                        session_return_pct, mfe_pct, return_30m_pct, return_60m_pct,
                        first_strong_time, session_high_time,
                        primary_status, primary_blocker,
                        buy_signal_count, approved_buy_count, rejected_buy_count,
                        sell_signal_count,
                        auto_buy_candidate_count, auto_buy_strong_count,
                        auto_buy_watch_count, auto_buy_submitted_count,
                        auto_buy_max_score, auto_buy_first_candidate_time,
                        auto_buy_first_strong_time,
                        prediction_score, prediction_decision, prediction_confidence,
                        prediction_sample_size, prediction_timing_score,
                        prediction_trend_score, prediction_trend_label,
                        raw_json, generated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    ON CONFLICT(market_date, symbol, min_session_pct) DO UPDATE SET
                        signal_source = excluded.signal_source,
                        session_return_pct = excluded.session_return_pct,
                        mfe_pct = excluded.mfe_pct,
                        return_30m_pct = excluded.return_30m_pct,
                        return_60m_pct = excluded.return_60m_pct,
                        first_strong_time = excluded.first_strong_time,
                        session_high_time = excluded.session_high_time,
                        primary_status = excluded.primary_status,
                        primary_blocker = excluded.primary_blocker,
                        buy_signal_count = excluded.buy_signal_count,
                        approved_buy_count = excluded.approved_buy_count,
                        rejected_buy_count = excluded.rejected_buy_count,
                        sell_signal_count = excluded.sell_signal_count,
                        auto_buy_candidate_count = excluded.auto_buy_candidate_count,
                        auto_buy_strong_count = excluded.auto_buy_strong_count,
                        auto_buy_watch_count = excluded.auto_buy_watch_count,
                        auto_buy_submitted_count = excluded.auto_buy_submitted_count,
                        auto_buy_max_score = excluded.auto_buy_max_score,
                        auto_buy_first_candidate_time = excluded.auto_buy_first_candidate_time,
                        auto_buy_first_strong_time = excluded.auto_buy_first_strong_time,
                        prediction_score = excluded.prediction_score,
                        prediction_decision = excluded.prediction_decision,
                        prediction_confidence = excluded.prediction_confidence,
                        prediction_sample_size = excluded.prediction_sample_size,
                        prediction_timing_score = excluded.prediction_timing_score,
                        prediction_trend_score = excluded.prediction_trend_score,
                        prediction_trend_label = excluded.prediction_trend_label,
                        raw_json = excluded.raw_json,
                        generated_at = excluded.generated_at
                    """,
                    (
                        target_date,
                        result.get("symbol"),
                        result.get("signal_source"),
                        min_session_pct,
                        result.get("session_return_pct"),
                        result.get("mfe_pct"),
                        result.get("return_30m_pct"),
                        result.get("return_60m_pct"),
                        result.get("first_strong_time"),
                        result.get("session_high_time"),
                        result.get("primary_status"),
                        result.get("primary_blocker"),
                        result.get("buy_signal_count"),
                        result.get("approved_buy_count"),
                        result.get("rejected_buy_count"),
                        result.get("sell_signal_count"),
                        result.get("auto_buy_candidate_count"),
                        result.get("auto_buy_strong_count"),
                        result.get("auto_buy_watch_count"),
                        result.get("auto_buy_submitted_count"),
                        result.get("auto_buy_max_score"),
                        result.get("auto_buy_first_candidate_time"),
                        result.get("auto_buy_first_strong_time"),
                        result.get("prediction_score"),
                        result.get("prediction_decision"),
                        result.get("prediction_confidence"),
                        result.get("prediction_sample_size"),
                        result.get("prediction_timing_score"),
                        result.get("prediction_trend_score"),
                        result.get("prediction_trend_label"),
                        json.dumps(result, sort_keys=True, default=str),
                        generated_at,
                    ),
                )
                rows_written += 1
        return rows_written
