"""Repository for curated trading education corpus ingestion."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class TradingEducationRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def init_table(self) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS trading_education_pages (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    source_key TEXT NOT NULL,
                    source_name TEXT NOT NULL,
                    source_tier TEXT,
                    url TEXT NOT NULL UNIQUE,
                    title TEXT,
                    retrieved_at TEXT NOT NULL,
                    content_hash TEXT NOT NULL,
                    summary TEXT,
                    concept_keys TEXT,
                    related_features TEXT,
                    source_policy_version TEXT NOT NULL,
                    corpus_version TEXT NOT NULL,
                    runtime_effect TEXT NOT NULL,
                    status TEXT NOT NULL,
                    error TEXT,
                    extraction_confidence REAL,
                    extraction_warnings TEXT,
                    ingestion_method TEXT
                )
                """
            )
            existing_cols = {
                row["name"]
                for row in con.execute("PRAGMA table_info(trading_education_pages)").fetchall()
            }
            for name, col_type in (
                ("extraction_confidence", "REAL"),
                ("extraction_warnings", "TEXT"),
                ("ingestion_method", "TEXT"),
            ):
                if name not in existing_cols:
                    con.execute(f"ALTER TABLE trading_education_pages ADD COLUMN {name} {col_type}")
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_trading_education_pages_source
                ON trading_education_pages(source_key, retrieved_at)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_trading_education_pages_status
                ON trading_education_pages(status, retrieved_at)
                """
            )

    def upsert_page(self, row: dict[str, Any]) -> None:
        self.init_table()
        with get_connection(self.db_path) as con:
            con.execute(
                """
                INSERT INTO trading_education_pages (
                    source_key,
                    source_name,
                    source_tier,
                    url,
                    title,
                    retrieved_at,
                    content_hash,
                    summary,
                    concept_keys,
                    related_features,
                    source_policy_version,
                    corpus_version,
                    runtime_effect,
                    status,
                    error,
                    extraction_confidence,
                    extraction_warnings,
                    ingestion_method
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(url) DO UPDATE SET
                    source_key = excluded.source_key,
                    source_name = excluded.source_name,
                    source_tier = excluded.source_tier,
                    title = excluded.title,
                    retrieved_at = excluded.retrieved_at,
                    content_hash = excluded.content_hash,
                    summary = excluded.summary,
                    concept_keys = excluded.concept_keys,
                    related_features = excluded.related_features,
                    source_policy_version = excluded.source_policy_version,
                    corpus_version = excluded.corpus_version,
                    runtime_effect = excluded.runtime_effect,
                    status = excluded.status,
                    error = excluded.error,
                    extraction_confidence = excluded.extraction_confidence,
                    extraction_warnings = excluded.extraction_warnings,
                    ingestion_method = excluded.ingestion_method
                """,
                (
                    row.get("source_key"),
                    row.get("source_name"),
                    row.get("source_tier"),
                    row.get("url"),
                    row.get("title"),
                    row.get("retrieved_at"),
                    row.get("content_hash"),
                    row.get("summary"),
                    row.get("concept_keys"),
                    row.get("related_features"),
                    row.get("source_policy_version"),
                    row.get("corpus_version"),
                    row.get("runtime_effect"),
                    row.get("status"),
                    row.get("error"),
                    row.get("extraction_confidence"),
                    row.get("extraction_warnings"),
                    row.get("ingestion_method"),
                ),
            )

    def summary(self) -> dict[str, Any]:
        self.init_table()
        with get_connection(self.db_path) as con:
            totals = con.execute(
                """
                SELECT
                    COUNT(*) AS rows,
                    SUM(CASE WHEN status = 'stored' THEN 1 ELSE 0 END) AS stored,
                    SUM(CASE WHEN status = 'needs_review' THEN 1 ELSE 0 END) AS needs_review,
                    SUM(CASE WHEN status != 'stored' THEN 1 ELSE 0 END) AS failed,
                    AVG(CASE WHEN status IN ('stored', 'needs_review') THEN extraction_confidence END) AS avg_confidence,
                    MAX(retrieved_at) AS latest_retrieved_at
                FROM trading_education_pages
                """
            ).fetchone()
            by_source = con.execute(
                """
                SELECT source_key, status, COUNT(*) AS rows, MAX(retrieved_at) AS latest_retrieved_at
                FROM trading_education_pages
                GROUP BY source_key, status
                ORDER BY source_key ASC, status ASC
                """
            ).fetchall()
            by_concept = con.execute(
                """
                SELECT concept_keys, COUNT(*) AS rows
                FROM trading_education_pages
                WHERE status = 'stored' AND concept_keys IS NOT NULL AND concept_keys != ''
                GROUP BY concept_keys
                ORDER BY rows DESC
                LIMIT 20
                """
            ).fetchall()
        return {
            "rows": int((totals or {})["rows"] or 0),
            "stored": int((totals or {})["stored"] or 0),
            "needs_review": int((totals or {})["needs_review"] or 0),
            "failed": int((totals or {})["failed"] or 0),
            "avg_confidence": float((totals or {})["avg_confidence"] or 0.0),
            "latest_retrieved_at": (totals or {})["latest_retrieved_at"],
            "by_source": [dict(row) for row in by_source],
            "by_concept": [dict(row) for row in by_concept],
        }

    def recent_pages(self, *, limit: int = 20, stored_only: bool = False) -> list[dict[str, Any]]:
        self.init_table()
        where = "WHERE status = 'stored'" if stored_only else ""
        with get_connection(self.db_path) as con:
            rows = con.execute(
                f"""
                SELECT
                    source_key,
                    source_tier,
                    url,
                    title,
                    retrieved_at,
                    summary,
                    concept_keys,
                    related_features,
                    status,
                    error,
                    extraction_confidence,
                    extraction_warnings,
                    ingestion_method
                FROM trading_education_pages
                {where}
                ORDER BY retrieved_at DESC, id DESC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]

    def review_rows(self, *, limit: int = 30) -> list[dict[str, Any]]:
        self.init_table()
        with get_connection(self.db_path) as con:
            rows = con.execute(
                """
                SELECT
                    source_key,
                    source_tier,
                    url,
                    title,
                    retrieved_at,
                    concept_keys,
                    related_features,
                    status,
                    error,
                    extraction_confidence,
                    extraction_warnings,
                    ingestion_method
                FROM trading_education_pages
                WHERE status != 'stored'
                   OR extraction_confidence IS NULL
                   OR extraction_confidence < 0.55
                   OR extraction_warnings IS NOT NULL
                ORDER BY
                    CASE
                        WHEN status = 'needs_review' THEN 0
                        WHEN status = 'schema_failed' THEN 1
                        WHEN status = 'fetch_failed' THEN 2
                        ELSE 3
                    END,
                    retrieved_at DESC,
                    url ASC
                LIMIT ?
                """,
                (int(limit),),
            ).fetchall()
        return [dict(row) for row in rows]
