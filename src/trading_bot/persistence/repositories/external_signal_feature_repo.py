"""Point-in-time external signal feature persistence."""

from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection

EXTERNAL_SIGNAL_FEATURE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS external_signal_features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    feature_ts TEXT NOT NULL,
    available_at TEXT NOT NULL,
    source TEXT NOT NULL,
    feature_family TEXT NOT NULL,
    feature_name TEXT NOT NULL,
    feature_value_numeric REAL,
    feature_value_text TEXT,
    lookback_window TEXT,
    release_lag_seconds REAL,
    source_url_or_ref TEXT,
    revision_policy TEXT NOT NULL DEFAULT 'point_in_time_as_reported',
    raw_json TEXT,
    created_at TEXT NOT NULL DEFAULT (datetime('now')),
    UNIQUE (
        symbol,
        feature_ts,
        available_at,
        source,
        feature_family,
        feature_name
    )
)
"""
SCHEDULED_KNOWN_BEFORE_EVENT_POLICIES = {
    "scheduled_known_before_event",
    "calendar_known_before_event",
}


@dataclass(frozen=True)
class ExternalSignalFeature:
    symbol: str
    feature_ts: str
    available_at: str
    source: str
    feature_family: str
    feature_name: str
    feature_value_numeric: float | None = None
    feature_value_text: str | None = None
    lookback_window: str | None = None
    release_lag_seconds: float | None = None
    source_url_or_ref: str | None = None
    revision_policy: str = "point_in_time_as_reported"
    raw_json: dict[str, Any] | None = None


def _clean_symbol(value: Any) -> str:
    symbol = str(value or "").strip().upper()
    return symbol or "*"


def _clean_required(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"{field} is required")
    return text


def _float_or_none(value: Any) -> float | None:
    if value in (None, ""):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result == result else None


def feature_from_mapping(payload: dict[str, Any]) -> ExternalSignalFeature:
    numeric = _float_or_none(
        payload.get("feature_value_numeric", payload.get("value_numeric", payload.get("value")))
    )
    text_value = payload.get("feature_value_text", payload.get("value_text"))
    if text_value is None and numeric is None and payload.get("value") not in (None, ""):
        text_value = str(payload.get("value"))
    raw_json = payload.get("raw_json")
    if raw_json is not None and not isinstance(raw_json, dict):
        raw_json = {"raw": raw_json}
    return ExternalSignalFeature(
        symbol=_clean_symbol(payload.get("symbol")),
        feature_ts=_clean_required(payload.get("feature_ts"), "feature_ts"),
        available_at=_clean_required(payload.get("available_at"), "available_at"),
        source=_clean_required(payload.get("source"), "source"),
        feature_family=_clean_required(payload.get("feature_family"), "feature_family"),
        feature_name=_clean_required(payload.get("feature_name"), "feature_name"),
        feature_value_numeric=numeric,
        feature_value_text=str(text_value) if text_value not in (None, "") else None,
        lookback_window=(
            str(payload.get("lookback_window")) if payload.get("lookback_window") else None
        ),
        release_lag_seconds=_float_or_none(payload.get("release_lag_seconds")),
        source_url_or_ref=(
            str(payload.get("source_url_or_ref") or payload.get("source_url"))
            if payload.get("source_url_or_ref") or payload.get("source_url")
            else None
        ),
        revision_policy=str(payload.get("revision_policy") or "point_in_time_as_reported"),
        raw_json=raw_json,
    )


class ExternalSignalFeatureRepository:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = db_path or DB_PATH

    def init_table(self) -> None:
        with get_connection(self.db_path) as con:
            con.execute(EXTERNAL_SIGNAL_FEATURE_TABLE_SQL)
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_external_signal_features_symbol_available
                ON external_signal_features(symbol, available_at)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_external_signal_features_family_available
                ON external_signal_features(feature_family, feature_name, available_at)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_external_signal_features_source
                ON external_signal_features(source, feature_ts)
                """
            )

    def upsert_many(self, features: list[ExternalSignalFeature]) -> int:
        if not features:
            return 0
        self.init_table()
        rows = [
            (
                feature.symbol,
                feature.feature_ts,
                feature.available_at,
                feature.source,
                feature.feature_family,
                feature.feature_name,
                feature.feature_value_numeric,
                feature.feature_value_text,
                feature.lookback_window,
                feature.release_lag_seconds,
                feature.source_url_or_ref,
                feature.revision_policy,
                json.dumps(feature.raw_json, sort_keys=True) if feature.raw_json else None,
            )
            for feature in features
        ]
        with get_connection(self.db_path) as con:
            before = con.total_changes
            con.executemany(
                """
                INSERT INTO external_signal_features (
                    symbol, feature_ts, available_at, source, feature_family, feature_name,
                    feature_value_numeric, feature_value_text, lookback_window,
                    release_lag_seconds, source_url_or_ref, revision_policy, raw_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT (
                    symbol, feature_ts, available_at, source, feature_family, feature_name
                ) DO UPDATE SET
                    feature_value_numeric = excluded.feature_value_numeric,
                    feature_value_text = excluded.feature_value_text,
                    lookback_window = excluded.lookback_window,
                    release_lag_seconds = excluded.release_lag_seconds,
                    source_url_or_ref = excluded.source_url_or_ref,
                    revision_policy = excluded.revision_policy,
                    raw_json = excluded.raw_json
                """,
                rows,
            )
            return con.total_changes - before

    def as_of_features(
        self,
        *,
        symbol: str,
        decision_ts: str,
        max_rows: int = 500,
    ) -> dict[str, Any]:
        self.init_table()
        normalized = _clean_symbol(symbol)
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT *
                FROM external_signal_features
                WHERE symbol IN (?, '*')
                  AND available_at <= ?
                ORDER BY available_at DESC, feature_ts DESC, id DESC
                LIMIT ?
                """,
                (normalized, decision_ts, int(max_rows)),
            ).fetchall()
        latest: dict[str, dict[str, Any]] = {}
        for row in rows:
            key = f"external.{row['feature_family']}.{row['feature_name']}"
            if key in latest:
                continue
            latest[key] = dict(row)
        return latest

    def rows_between(
        self, *, start: str | None = None, end: str | None = None
    ) -> list[dict[str, Any]]:
        self.init_table()
        where = []
        params: list[Any] = []
        if start:
            where.append("available_at >= ?")
            params.append(start)
        if end:
            where.append("available_at < ?")
            params.append(end)
        sql = "SELECT * FROM external_signal_features"
        if where:
            sql += " WHERE " + " AND ".join(where)
        sql += " ORDER BY available_at, symbol, feature_family, feature_name"
        with get_connection(self.db_path) as con:
            return [dict(row) for row in con.execute(sql, params).fetchall()]

    def leakage_violations(self) -> int:
        self.init_table()
        allowed_policy_placeholders = ", ".join("?" for _ in SCHEDULED_KNOWN_BEFORE_EVENT_POLICIES)
        with get_connection(self.db_path) as con:
            row = con.execute(
                f"""
                SELECT COUNT(*) AS n
                FROM external_signal_features
                WHERE available_at < feature_ts
                  AND revision_policy NOT IN ({allowed_policy_placeholders})
                """,
                tuple(sorted(SCHEDULED_KNOWN_BEFORE_EVENT_POLICIES)),
            ).fetchone()
        return int(row["n"] if isinstance(row, sqlite3.Row) else row[0])
