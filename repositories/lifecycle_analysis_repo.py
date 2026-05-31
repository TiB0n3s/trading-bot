"""Repository boundary for entry/exit lifecycle analysis rows."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class LifecycleAnalysisRepository:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = db_path or DB_PATH

    @staticmethod
    def _table_exists(con, table: str) -> bool:
        return con.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (table,),
        ).fetchone() is not None

    def lifecycle_rows(
        self,
        *,
        start_date: str,
        end_date: str,
        symbol: str | None = None,
        limit: int | None = None,
    ) -> list[Any]:
        with get_connection(self.db_path) as con:
            if not self._table_exists(con, "decision_snapshots"):
                return []

            has_exit = self._table_exists(con, "exit_snapshots")
            has_rejected = self._table_exists(con, "rejected_signal_outcomes")

            exit_select = """
                es.id AS exit_snapshot_id,
                es.exit_timestamp,
                es.exit_trigger,
                es.exit_source,
                es.realized_pnl,
                es.realized_return_pct,
                es.mfe_pct,
                es.capture_ratio,
                es.max_adverse_excursion_pct,
                es.avoided_drawdown_pct,
                es.missed_upside_pct,
                es.reentry_window_summary,
                es.canonical_exit_version,
                es.canonical_exit_hash,
                es.entry_canonical_intelligence_hash
            """ if has_exit else """
                NULL AS exit_snapshot_id,
                NULL AS exit_timestamp,
                NULL AS exit_trigger,
                NULL AS exit_source,
                NULL AS realized_pnl,
                NULL AS realized_return_pct,
                NULL AS mfe_pct,
                NULL AS capture_ratio,
                NULL AS max_adverse_excursion_pct,
                NULL AS avoided_drawdown_pct,
                NULL AS missed_upside_pct,
                NULL AS reentry_window_summary,
                NULL AS canonical_exit_version,
                NULL AS canonical_exit_hash,
                NULL AS entry_canonical_intelligence_hash
            """
            exit_join = """
                LEFT JOIN exit_snapshots es
                  ON es.entry_trade_id = ds.trade_id
                  OR (
                    es.entry_canonical_intelligence_hash IS NOT NULL
                    AND es.entry_canonical_intelligence_hash = ds.canonical_intelligence_hash
                  )
            """ if has_exit else ""

            rejected_select = """
                rso.id AS rejected_outcome_id,
                rso.label_status AS rejected_label_status,
                rso.return_30m AS rejected_return_30m,
                rso.return_60m AS rejected_return_60m,
                rso.max_favorable_60m AS rejected_max_favorable_60m,
                rso.max_adverse_60m AS rejected_max_adverse_60m,
                rso.canonical_intelligence_hash AS rejected_canonical_intelligence_hash
            """ if has_rejected else """
                NULL AS rejected_outcome_id,
                NULL AS rejected_label_status,
                NULL AS rejected_return_30m,
                NULL AS rejected_return_60m,
                NULL AS rejected_max_favorable_60m,
                NULL AS rejected_max_adverse_60m,
                NULL AS rejected_canonical_intelligence_hash
            """
            rejected_join = """
                LEFT JOIN rejected_signal_outcomes rso
                  ON rso.decision_snapshot_id = ds.id
                  OR rso.trade_id = ds.trade_id
            """ if has_rejected else ""

            clauses = [
                "substr(ds.decision_time, 1, 10) BETWEEN ? AND ?",
                "LOWER(COALESCE(ds.action, '')) IN ('buy', 'sell')",
            ]
            params: list[Any] = [start_date, end_date]
            if symbol:
                clauses.append("UPPER(ds.symbol) = ?")
                params.append(symbol.upper())

            limit_sql = ""
            if limit is not None:
                limit_sql = "LIMIT ?"
                params.append(int(limit))

            return con.execute(
                f"""
                SELECT
                    ds.id AS decision_snapshot_id,
                    ds.trade_id,
                    ds.decision_time,
                    ds.symbol,
                    ds.action,
                    ds.approved,
                    ds.final_decision,
                    ds.rejection_reason,
                    ds.canonical_intelligence_version AS entry_canonical_intelligence_version,
                    ds.canonical_intelligence_hash AS entry_canonical_intelligence_hash,
                    {exit_select},
                    {rejected_select}
                FROM decision_snapshots ds
                {exit_join}
                {rejected_join}
                WHERE {' AND '.join(clauses)}
                ORDER BY ds.decision_time ASC, ds.id ASC
                {limit_sql}
                """,
                params,
            ).fetchall()
