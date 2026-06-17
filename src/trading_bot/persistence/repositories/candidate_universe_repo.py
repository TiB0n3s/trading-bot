"""Repository boundary for canonical candidate-universe persistence."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection, get_read_connection


class CandidateUniverseRepository:
    """Persist scored candidates before final thresholding.

    This table is intentionally broader than auto-buy candidates. It can hold
    entry candidates, near-threshold candidates, and exit candidates considered
    but not taken so downstream training is less biased toward acted-on paths.
    """

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = db_path or DB_PATH
        self._initialized = False

    def init_table(self) -> None:
        if self._initialized:
            return
        with get_connection(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS candidate_universe (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    candidate_ts TEXT NOT NULL,
                    symbol TEXT NOT NULL,
                    action TEXT NOT NULL,
                    candidate_kind TEXT NOT NULL,
                    candidate_status TEXT NOT NULL,
                    score REAL,
                    threshold REAL,
                    threshold_distance REAL,
                    decision TEXT,
                    reason TEXT,
                    source TEXT,
                    setup_label TEXT,
                    regime TEXT,
                    session_phase TEXT,
                    canonical_intelligence_hash TEXT,
                    canonical_intelligence_version TEXT,
                    candidate_json TEXT NOT NULL,
                    runtime_effect TEXT NOT NULL DEFAULT 'candidate_capture_only_no_live_authority'
                )
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_candidate_universe_time
                ON candidate_universe(candidate_ts)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_candidate_universe_symbol_time
                ON candidate_universe(symbol, candidate_ts)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_candidate_universe_kind_status
                ON candidate_universe(candidate_kind, candidate_status)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_candidate_universe_date_kind_status
                ON candidate_universe(substr(candidate_ts, 1, 10), candidate_kind, candidate_status)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_candidate_universe_kind_status_date
                ON candidate_universe(candidate_kind, candidate_status, substr(candidate_ts, 1, 10))
                """
            )
        self._initialized = True

    @staticmethod
    def _table_exists(con, table: str) -> bool:
        return (
            con.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            is not None
        )

    @staticmethod
    def _forward_outcome_sql() -> str:
        paths = (
            "$.forward_return_pct",
            "$.return_60m",
            "$.return_30m",
            "$.return_eod",
            "$.forward_mfe_pct",
            "$.max_favorable_60m",
            "$.max_favorable_30m",
            "$.max_favorable_eod",
            "$.candidate.forward_return_pct",
            "$.candidate.return_60m",
            "$.candidate.return_30m",
            "$.candidate.return_eod",
            "$.candidate.forward_mfe_pct",
            "$.candidate.max_favorable_60m",
            "$.candidate.max_favorable_30m",
            "$.candidate.max_favorable_eod",
        )
        checks = " OR ".join(f"json_type(candidate_json, '{path}') IS NOT NULL" for path in paths)
        return f"(json_valid(candidate_json) AND ({checks}))"

    @staticmethod
    def _non_taken_sql() -> str:
        return """
        (
            COALESCE(candidate_status, '') != 'taken'
            AND LOWER(COALESCE(decision, '')) NOT IN ('submitted', 'approved', 'buy')
            AND (
                candidate_status IN (
                    'near_threshold',
                    'scored_not_taken',
                    'skipped',
                    'watch',
                    'exit_considered_not_taken'
                )
                OR COALESCE(candidate_status, '') != ''
                OR COALESCE(decision, '') != ''
            )
        )
        """

    def insert_candidate(self, row: dict[str, Any]) -> int:
        self.init_table()
        columns = list(row.keys())
        placeholders = ", ".join(["?"] * len(columns))
        with get_connection(self.db_path) as con:
            cur = con.execute(
                f"""
                INSERT INTO candidate_universe ({", ".join(columns)})
                VALUES ({placeholders})
                """,
                [row[col] for col in columns],
            )
            return int(cur.lastrowid)

    def rows_for_date(
        self,
        target_date: str,
        *,
        symbol: str | None = None,
        candidate_kind: str | None = None,
    ) -> list[Any]:
        if not Path(self.db_path).exists():
            return []
        clauses = ["substr(candidate_ts, 1, 10) = ?"]
        params: list[Any] = [target_date]
        if symbol:
            clauses.append("UPPER(symbol) = ?")
            params.append(symbol.upper())
        if candidate_kind:
            clauses.append("candidate_kind = ?")
            params.append(candidate_kind)
        with get_read_connection(self.db_path) as con:
            if not self._table_exists(con, "candidate_universe"):
                return []
            return con.execute(
                f"""
                SELECT *
                FROM candidate_universe
                WHERE {" AND ".join(clauses)}
                ORDER BY candidate_ts ASC, id ASC
                """,
                params,
            ).fetchall()

    def rows_between(
        self,
        start_date: str,
        end_date: str,
        *,
        symbol: str | None = None,
        candidate_kind: str | None = None,
        candidate_statuses: tuple[str, ...] | None = None,
        limit: int | None = None,
    ) -> list[Any]:
        if not Path(self.db_path).exists():
            return []
        clauses = ["substr(candidate_ts, 1, 10) BETWEEN ? AND ?"]
        params: list[Any] = [start_date, end_date]
        if symbol:
            clauses.append("UPPER(symbol) = ?")
            params.append(symbol.upper())
        if candidate_kind:
            clauses.append("candidate_kind = ?")
            params.append(candidate_kind)
        if candidate_statuses:
            placeholders = ", ".join("?" for _ in candidate_statuses)
            clauses.append(f"candidate_status IN ({placeholders})")
            params.extend(candidate_statuses)
        with get_read_connection(self.db_path) as con:
            if not self._table_exists(con, "candidate_universe"):
                return []
            return con.execute(
                f"""
                SELECT *
                FROM candidate_universe
                WHERE {" AND ".join(clauses)}
                ORDER BY candidate_ts ASC, id ASC
                {f"LIMIT {int(limit)}" if limit and limit > 0 else ""}
                """,
                params,
            ).fetchall()

    def summary_between(
        self,
        start_date: str,
        end_date: str,
        *,
        symbol: str | None = None,
        candidate_kind: str | None = None,
        candidate_statuses: tuple[str, ...] | None = None,
    ) -> dict[str, Any]:
        empty = {
            "rows": 0,
            "sessions": 0,
            "scored_rows": 0,
            "near_threshold": 0,
            "scored_not_taken": 0,
            "taken": 0,
            "exit_considered_not_taken": 0,
            "by_status": {},
            "by_kind": {},
            "rows_with_forward_outcome": 0,
            "missing_forward_outcome": 0,
            "forward_outcome_coverage_rate": None,
            "non_taken_rows": 0,
            "non_taken_with_forward_outcome": 0,
            "non_taken_forward_outcome_coverage_rate": None,
        }
        if not Path(self.db_path).exists():
            return empty
        clauses = ["substr(candidate_ts, 1, 10) BETWEEN ? AND ?"]
        params: list[Any] = [start_date, end_date]
        if symbol:
            clauses.append("UPPER(symbol) = ?")
            params.append(symbol.upper())
        if candidate_kind:
            clauses.append("candidate_kind = ?")
            params.append(candidate_kind)
        if candidate_statuses:
            placeholders = ", ".join("?" for _ in candidate_statuses)
            clauses.append(f"candidate_status IN ({placeholders})")
            params.extend(candidate_statuses)

        where_sql = " AND ".join(clauses)
        forward_sql = self._forward_outcome_sql()
        non_taken_sql = self._non_taken_sql()
        with get_read_connection(self.db_path) as con:
            if not self._table_exists(con, "candidate_universe"):
                return empty
            summary = con.execute(
                f"""
                SELECT
                    COUNT(*) AS rows,
                    COUNT(DISTINCT substr(candidate_ts, 1, 10)) AS sessions,
                    SUM(CASE WHEN score IS NOT NULL THEN 1 ELSE 0 END) AS scored_rows,
                    SUM(CASE WHEN candidate_status = 'near_threshold' THEN 1 ELSE 0 END)
                        AS near_threshold,
                    SUM(CASE WHEN candidate_status = 'scored_not_taken' THEN 1 ELSE 0 END)
                        AS scored_not_taken,
                    SUM(CASE WHEN candidate_status = 'taken' THEN 1 ELSE 0 END) AS taken,
                    SUM(CASE WHEN candidate_status = 'exit_considered_not_taken' THEN 1 ELSE 0 END)
                        AS exit_considered_not_taken,
                    SUM(CASE WHEN {forward_sql} THEN 1 ELSE 0 END) AS rows_with_forward_outcome,
                    SUM(CASE WHEN {non_taken_sql} THEN 1 ELSE 0 END) AS non_taken_rows,
                    SUM(CASE WHEN ({non_taken_sql}) AND ({forward_sql}) THEN 1 ELSE 0 END)
                        AS non_taken_with_forward_outcome
                FROM candidate_universe
                WHERE {where_sql}
                """,
                params,
            ).fetchone()
            by_status = con.execute(
                f"""
                SELECT COALESCE(candidate_status, 'unknown') AS key, COUNT(*) AS rows
                FROM candidate_universe
                WHERE {where_sql}
                GROUP BY COALESCE(candidate_status, 'unknown')
                """,
                params,
            ).fetchall()
            by_kind = con.execute(
                f"""
                SELECT COALESCE(candidate_kind, 'unknown') AS key, COUNT(*) AS rows
                FROM candidate_universe
                WHERE {where_sql}
                GROUP BY COALESCE(candidate_kind, 'unknown')
                """,
                params,
            ).fetchall()

        total = int(summary["rows"] or 0)
        forward = int(summary["rows_with_forward_outcome"] or 0)
        non_taken = int(summary["non_taken_rows"] or 0)
        non_taken_forward = int(summary["non_taken_with_forward_outcome"] or 0)
        return {
            "rows": total,
            "sessions": int(summary["sessions"] or 0),
            "scored_rows": int(summary["scored_rows"] or 0),
            "near_threshold": int(summary["near_threshold"] or 0),
            "scored_not_taken": int(summary["scored_not_taken"] or 0),
            "taken": int(summary["taken"] or 0),
            "exit_considered_not_taken": int(summary["exit_considered_not_taken"] or 0),
            "by_status": {str(row["key"]): int(row["rows"] or 0) for row in by_status},
            "by_kind": {str(row["key"]): int(row["rows"] or 0) for row in by_kind},
            "rows_with_forward_outcome": forward,
            "missing_forward_outcome": total - forward,
            "forward_outcome_coverage_rate": round(forward / total, 4) if total else None,
            "non_taken_rows": non_taken,
            "non_taken_with_forward_outcome": non_taken_forward,
            "non_taken_forward_outcome_coverage_rate": (
                round(non_taken_forward / non_taken, 4) if non_taken else None
            ),
        }

    def learned_tiebreaker_stats(
        self,
        start_date: str,
        end_date: str,
        *,
        symbol: str,
        pattern: str,
        candidate_statuses: tuple[str, ...],
        limit: int | None = None,
    ) -> dict[str, dict[str, Any]]:
        empty_stats = {
            "sample_size": 0,
            "win_rate": None,
            "avg_return_pct": None,
            "avg_mfe_pct": None,
            "avg_mae_pct": None,
        }
        if not Path(self.db_path).exists():
            return {"symbol_pattern_stats": dict(empty_stats), "pattern_stats": dict(empty_stats)}
        status_placeholders = ", ".join("?" for _ in candidate_statuses)
        limit_sql = f"LIMIT {int(limit)}" if limit and limit > 0 else ""
        base_params: list[Any] = [start_date, end_date, *candidate_statuses]

        sql = f"""
            WITH base AS (
                SELECT symbol, setup_label, candidate_json
                FROM candidate_universe
                WHERE substr(candidate_ts, 1, 10) BETWEEN ? AND ?
                  AND candidate_kind = 'entry'
                  AND candidate_status IN ({status_placeholders})
                ORDER BY candidate_ts ASC, id ASC
                {limit_sql}
            ),
            features AS (
                SELECT
                    UPPER(symbol) AS symbol,
                    COALESCE(
                        json_extract(candidate_json, '$.candidate.symbol_pattern'),
                        json_extract(candidate_json, '$.symbol_pattern'),
                        json_extract(candidate_json, '$.candidate.pattern_label'),
                        setup_label,
                        'unknown'
                    ) AS pattern,
                    COALESCE(
                        json_extract(candidate_json, '$.forward_return_pct'),
                        json_extract(candidate_json, '$.return_60m'),
                        json_extract(candidate_json, '$.return_30m'),
                        json_extract(candidate_json, '$.return_eod')
                    ) AS ret,
                    COALESCE(
                        json_extract(candidate_json, '$.forward_mfe_pct'),
                        json_extract(candidate_json, '$.max_favorable_60m'),
                        json_extract(candidate_json, '$.max_favorable_30m'),
                        json_extract(candidate_json, '$.max_favorable_eod')
                    ) AS mfe,
                    COALESCE(
                        json_extract(candidate_json, '$.forward_mae_pct'),
                        json_extract(candidate_json, '$.max_adverse_60m'),
                        json_extract(candidate_json, '$.max_adverse_30m'),
                        json_extract(candidate_json, '$.max_adverse_eod')
                    ) AS mae
                FROM base
            )
            SELECT
                'symbol_pattern_stats' AS bucket,
                COUNT(ret) AS sample_size,
                AVG(CASE WHEN ret IS NOT NULL THEN CASE WHEN ret > 0 THEN 1.0 ELSE 0.0 END END)
                    AS win_rate,
                AVG(ret) AS avg_return_pct,
                AVG(mfe) AS avg_mfe_pct,
                AVG(mae) AS avg_mae_pct
            FROM features
            WHERE pattern = ?
              AND symbol = ?
            UNION ALL
            SELECT
                'pattern_stats' AS bucket,
                COUNT(ret) AS sample_size,
                AVG(CASE WHEN ret IS NOT NULL THEN CASE WHEN ret > 0 THEN 1.0 ELSE 0.0 END END)
                    AS win_rate,
                AVG(ret) AS avg_return_pct,
                AVG(mfe) AS avg_mfe_pct,
                AVG(mae) AS avg_mae_pct
            FROM features
            WHERE pattern = ?
        """
        symbol_upper = str(symbol or "").upper()
        with get_read_connection(self.db_path) as con:
            if not self._table_exists(con, "candidate_universe"):
                return {
                    "symbol_pattern_stats": dict(empty_stats),
                    "pattern_stats": dict(empty_stats),
                }
            rows = con.execute(
                sql,
                [
                    *base_params,
                    pattern,
                    symbol_upper,
                    pattern,
                ],
            ).fetchall()

        result = {"symbol_pattern_stats": dict(empty_stats), "pattern_stats": dict(empty_stats)}
        for row in rows:
            result[str(row["bucket"])] = {
                "sample_size": int(row["sample_size"] or 0),
                "win_rate": round(float(row["win_rate"]), 4)
                if row["win_rate"] is not None
                else None,
                "avg_return_pct": round(float(row["avg_return_pct"]), 4)
                if row["avg_return_pct"] is not None
                else None,
                "avg_mfe_pct": round(float(row["avg_mfe_pct"]), 4)
                if row["avg_mfe_pct"] is not None
                else None,
                "avg_mae_pct": round(float(row["avg_mae_pct"]), 4)
                if row["avg_mae_pct"] is not None
                else None,
            }
        return result

    def update_candidate_json(self, candidate_id: int, payload: dict[str, Any]) -> None:
        self.init_table()
        with get_connection(self.db_path) as con:
            con.execute(
                """
                UPDATE candidate_universe
                SET candidate_json = ?
                WHERE id = ?
                """,
                (
                    json.dumps(payload, sort_keys=True, separators=(",", ":")),
                    int(candidate_id),
                ),
            )

    def update_candidate_json_many(self, updates: list[tuple[int, dict[str, Any]]]) -> None:
        if not updates:
            return
        self.init_table()
        rows = [
            (
                json.dumps(payload, sort_keys=True, separators=(",", ":")),
                int(candidate_id),
            )
            for candidate_id, payload in updates
        ]
        with get_connection(self.db_path) as con:
            con.executemany(
                """
                UPDATE candidate_universe
                SET candidate_json = ?
                WHERE id = ?
                """,
                rows,
            )

    def feature_snapshot_price_bars(
        self,
        *,
        symbol: str,
        target_date: str,
    ) -> list[dict[str, Any]]:
        if not Path(self.db_path).exists():
            return []
        with get_read_connection(self.db_path) as con:
            if not self._table_exists(con, "feature_snapshots"):
                return []
            rows = con.execute(
                """
                SELECT timestamp, last_price
                FROM feature_snapshots
                WHERE UPPER(symbol) = ?
                  AND substr(timestamp, 1, 10) = ?
                  AND last_price IS NOT NULL
                  AND last_price > 0
                ORDER BY timestamp ASC
                """,
                (str(symbol).upper(), target_date),
            ).fetchall()
        return [dict(row) for row in rows]
