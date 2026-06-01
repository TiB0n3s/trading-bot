"""Session momentum persistence helpers."""

from __future__ import annotations

from typing import Any

from db import DB_PATH, get_connection


class SessionMomentumRepository:
    def __init__(self, db_path=DB_PATH):
        self.db_path = db_path

    def init_table(self) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS session_momentum (
                    symbol TEXT PRIMARY KEY,
                    updated_at TEXT NOT NULL,
                    bar_count INTEGER,
                    session_open_price REAL,
                    latest_price REAL,
                    session_return_pct REAL,
                    momentum_5m_pct REAL,
                    momentum_15m_pct REAL,
                    momentum_30m_pct REAL,
                    momentum_60m_pct REAL,
                    momentum_120m_pct REAL,
                    vwap REAL,
                    distance_from_vwap_pct REAL,
                    trend_regime TEXT,
                    trend_persistence_score INTEGER,
                    pullback_with_trend_score INTEGER,
                    late_chase_maturity_score INTEGER,
                    reversal_attempt_score INTEGER,
                    trend_label TEXT,
                    trend_score INTEGER,
                    reason TEXT,
                    best_trend_score INTEGER,
                    best_session_return_pct REAL,
                    best_distance_from_vwap_pct REAL,
                    minutes_strong INTEGER,
                    strength_first_seen_at TEXT,
                    strength_last_seen_at TEXT,
                    pullback_from_session_high_pct REAL,
                    session_strength_seen INTEGER
                )
                """
            )

            existing = {
                r["name"]
                for r in con.execute("PRAGMA table_info(session_momentum)").fetchall()
            }
            for col, typ in (
                ("best_trend_score", "INTEGER"),
                ("momentum_60m_pct", "REAL"),
                ("momentum_120m_pct", "REAL"),
                ("trend_regime", "TEXT"),
                ("trend_persistence_score", "INTEGER"),
                ("pullback_with_trend_score", "INTEGER"),
                ("late_chase_maturity_score", "INTEGER"),
                ("reversal_attempt_score", "INTEGER"),
                ("best_session_return_pct", "REAL"),
                ("best_distance_from_vwap_pct", "REAL"),
                ("minutes_strong", "INTEGER"),
                ("strength_first_seen_at", "TEXT"),
                ("strength_last_seen_at", "TEXT"),
                ("pullback_from_session_high_pct", "REAL"),
                ("session_strength_seen", "INTEGER"),
            ):
                if col not in existing:
                    con.execute(f"ALTER TABLE session_momentum ADD COLUMN {col} {typ}")

    def get_latest(self, symbol: str) -> dict[str, Any] | None:
        self.init_table()
        with get_connection(self.db_path) as con:
            row = con.execute(
                """
                SELECT *
                FROM session_momentum
                WHERE symbol = ?
                """,
                (symbol.upper(),),
            ).fetchone()
        return dict(row) if row else None

    def upsert(self, row: dict[str, Any]) -> None:
        self.init_table()
        with get_connection(self.db_path) as con:
            con.execute(
                """
                INSERT INTO session_momentum (
                    symbol,
                    updated_at,
                    bar_count,
                    session_open_price,
                    latest_price,
                    session_return_pct,
                    momentum_5m_pct,
                    momentum_15m_pct,
                    momentum_30m_pct,
                    momentum_60m_pct,
                    momentum_120m_pct,
                    vwap,
                    distance_from_vwap_pct,
                    trend_regime,
                    trend_persistence_score,
                    pullback_with_trend_score,
                    late_chase_maturity_score,
                    reversal_attempt_score,
                    trend_label,
                    trend_score,
                    reason,
                    best_trend_score,
                    best_session_return_pct,
                    best_distance_from_vwap_pct,
                    minutes_strong,
                    strength_first_seen_at,
                    strength_last_seen_at,
                    pullback_from_session_high_pct,
                    session_strength_seen
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(symbol) DO UPDATE SET
                    updated_at=excluded.updated_at,
                    bar_count=excluded.bar_count,
                    session_open_price=excluded.session_open_price,
                    latest_price=excluded.latest_price,
                    session_return_pct=excluded.session_return_pct,
                    momentum_5m_pct=excluded.momentum_5m_pct,
                    momentum_15m_pct=excluded.momentum_15m_pct,
                    momentum_30m_pct=excluded.momentum_30m_pct,
                    momentum_60m_pct=excluded.momentum_60m_pct,
                    momentum_120m_pct=excluded.momentum_120m_pct,
                    vwap=excluded.vwap,
                    distance_from_vwap_pct=excluded.distance_from_vwap_pct,
                    trend_regime=excluded.trend_regime,
                    trend_persistence_score=excluded.trend_persistence_score,
                    pullback_with_trend_score=excluded.pullback_with_trend_score,
                    late_chase_maturity_score=excluded.late_chase_maturity_score,
                    reversal_attempt_score=excluded.reversal_attempt_score,
                    trend_label=excluded.trend_label,
                    trend_score=excluded.trend_score,
                    reason=excluded.reason,
                    best_trend_score=excluded.best_trend_score,
                    best_session_return_pct=excluded.best_session_return_pct,
                    best_distance_from_vwap_pct=excluded.best_distance_from_vwap_pct,
                    minutes_strong=excluded.minutes_strong,
                    strength_first_seen_at=excluded.strength_first_seen_at,
                    strength_last_seen_at=excluded.strength_last_seen_at,
                    pullback_from_session_high_pct=excluded.pullback_from_session_high_pct,
                    session_strength_seen=excluded.session_strength_seen
                """,
                (
                    row.get("symbol"),
                    row.get("updated_at"),
                    row.get("bar_count"),
                    row.get("session_open_price"),
                    row.get("latest_price"),
                    row.get("session_return_pct"),
                    row.get("momentum_5m_pct"),
                    row.get("momentum_15m_pct"),
                    row.get("momentum_30m_pct"),
                    row.get("momentum_60m_pct"),
                    row.get("momentum_120m_pct"),
                    row.get("vwap"),
                    row.get("distance_from_vwap_pct"),
                    row.get("trend_regime"),
                    row.get("trend_persistence_score"),
                    row.get("pullback_with_trend_score"),
                    row.get("late_chase_maturity_score"),
                    row.get("reversal_attempt_score"),
                    row.get("trend_label"),
                    row.get("trend_score"),
                    row.get("reason"),
                    row.get("best_trend_score"),
                    row.get("best_session_return_pct"),
                    row.get("best_distance_from_vwap_pct"),
                    row.get("minutes_strong"),
                    row.get("strength_first_seen_at"),
                    row.get("strength_last_seen_at"),
                    row.get("pullback_from_session_high_pct"),
                    row.get("session_strength_seen"),
                ),
            )


_default_repository: SessionMomentumRepository | None = None


def get_default_repository() -> SessionMomentumRepository:
    global _default_repository
    if _default_repository is None:
        _default_repository = SessionMomentumRepository()
    return _default_repository


def init_session_momentum_table() -> None:
    get_default_repository().init_table()


def upsert_session_momentum(row: dict[str, Any]) -> None:
    get_default_repository().upsert(row)


def get_latest_session_momentum(symbol: str) -> dict[str, Any] | None:
    return get_default_repository().get_latest(symbol)
