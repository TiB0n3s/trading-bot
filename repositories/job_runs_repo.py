"""Repository boundary for cron/operator job run ledger rows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class JobRunsRepository:
    def __init__(self, db_path: Path | str = DB_PATH):
        self.db_path = db_path

    def init_table(self) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS job_runs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    job_name TEXT NOT NULL,
                    started_at TEXT NOT NULL,
                    finished_at TEXT NOT NULL,
                    duration_sec REAL NOT NULL,
                    exit_code INTEGER,
                    lock_acquired INTEGER NOT NULL,
                    skipped_reason TEXT,
                    rows_written INTEGER,
                    warnings_count INTEGER,
                    artifact_path TEXT,
                    artifact_hash TEXT,
                    command TEXT
                )
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_job_runs_job_started
                ON job_runs(job_name, started_at)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_job_runs_finished
                ON job_runs(finished_at)
                """
            )

    def insert_run(self, row: dict[str, Any]) -> int:
        with get_connection(self.db_path) as con:
            cur = con.execute(
                """
                INSERT INTO job_runs (
                    job_name,
                    started_at,
                    finished_at,
                    duration_sec,
                    exit_code,
                    lock_acquired,
                    skipped_reason,
                    rows_written,
                    warnings_count,
                    artifact_path,
                    artifact_hash,
                    command
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    row.get("job_name"),
                    row.get("started_at"),
                    row.get("finished_at"),
                    row.get("duration_sec"),
                    row.get("exit_code"),
                    1 if row.get("lock_acquired") else 0,
                    row.get("skipped_reason"),
                    row.get("rows_written"),
                    row.get("warnings_count"),
                    row.get("artifact_path"),
                    row.get("artifact_hash"),
                    row.get("command"),
                ),
            )
            return int(cur.lastrowid)

    def recent_runs(self, *, limit: int = 50, job_name: str | None = None):
        params: list[Any] = []
        where = ["1=1"]
        if job_name:
            where.append("job_name = ?")
            params.append(job_name)
        params.append(limit)
        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT
                    id,
                    job_name,
                    started_at,
                    finished_at,
                    duration_sec,
                    exit_code,
                    lock_acquired,
                    skipped_reason,
                    rows_written,
                    warnings_count,
                    artifact_path,
                    artifact_hash,
                    command
                FROM job_runs
                WHERE {' AND '.join(where)}
                ORDER BY id DESC
                LIMIT ?
                """,
                params,
            ).fetchall()

    def runs_for_date(self, target_date: str, *, limit: int | None = None):
        params: list[Any] = [target_date]
        limit_sql = ""
        if limit is not None:
            limit_sql = "LIMIT ?"
            params.append(int(limit))

        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                SELECT
                    id,
                    job_name,
                    started_at,
                    finished_at,
                    duration_sec,
                    exit_code,
                    lock_acquired,
                    skipped_reason,
                    rows_written,
                    warnings_count,
                    artifact_path,
                    artifact_hash,
                    command
                FROM job_runs
                WHERE substr(started_at, 1, 10) = ?
                ORDER BY started_at ASC, id ASC
                {limit_sql}
                """,
                params,
            ).fetchall()

    def runs_between(self, start_date: str, end_date: str):
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT
                    id,
                    job_name,
                    started_at,
                    finished_at,
                    duration_sec,
                    exit_code,
                    lock_acquired,
                    skipped_reason,
                    rows_written,
                    warnings_count,
                    artifact_path,
                    artifact_hash,
                    command
                FROM job_runs
                WHERE substr(started_at, 1, 10) BETWEEN ? AND ?
                ORDER BY started_at ASC, id ASC
                """,
                (start_date, end_date),
            ).fetchall()
