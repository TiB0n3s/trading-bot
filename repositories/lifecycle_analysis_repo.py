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

    @staticmethod
    def _table_columns(con, table: str) -> set[str]:
        if not LifecycleAnalysisRepository._table_exists(con, table):
            return set()
        return {
            row["name"]
            for row in con.execute(f"PRAGMA table_info({table})").fetchall()
        }

    @staticmethod
    def _select(columns: set[str], alias: str, column: str, output: str | None = None) -> str:
        name = output or column
        if column in columns:
            return f"{alias}.{column} AS {name}"
        return f"NULL AS {name}"

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
            decision_cols = self._table_columns(con, "decision_snapshots")
            exit_cols = self._table_columns(con, "exit_snapshots")
            rejected_cols = self._table_columns(con, "rejected_signal_outcomes")
            sel = self._select

            exit_join_terms = []
            if has_exit:
                if "entry_trade_id" in exit_cols and "trade_id" in decision_cols:
                    exit_join_terms.append("es.entry_trade_id = ds.trade_id")
                if (
                    "entry_canonical_intelligence_hash" in exit_cols
                    and "canonical_intelligence_hash" in decision_cols
                ):
                    exit_join_terms.append(
                        """
                        (
                            es.entry_canonical_intelligence_hash IS NOT NULL
                            AND es.entry_canonical_intelligence_hash = ds.canonical_intelligence_hash
                        )
                        """
                    )
            can_join_exit = has_exit and bool(exit_join_terms)

            exit_select = """
                es.id AS exit_snapshot_id,
                {exit_timestamp},
                {exit_trigger},
                {exit_source},
                {realized_pnl},
                {realized_return_pct},
                {mfe_pct},
                {capture_ratio},
                {max_adverse_excursion_pct},
                {avoided_drawdown_pct},
                {missed_upside_pct},
                {reentry_window_summary},
                {canonical_exit_version},
                {canonical_exit_hash},
                {entry_canonical_intelligence_hash}
            """.format(
                exit_timestamp=sel(exit_cols, "es", "exit_timestamp"),
                exit_trigger=sel(exit_cols, "es", "exit_trigger"),
                exit_source=sel(exit_cols, "es", "exit_source"),
                realized_pnl=sel(exit_cols, "es", "realized_pnl"),
                realized_return_pct=sel(exit_cols, "es", "realized_return_pct"),
                mfe_pct=sel(exit_cols, "es", "mfe_pct"),
                capture_ratio=sel(exit_cols, "es", "capture_ratio"),
                max_adverse_excursion_pct=sel(exit_cols, "es", "max_adverse_excursion_pct"),
                avoided_drawdown_pct=sel(exit_cols, "es", "avoided_drawdown_pct"),
                missed_upside_pct=sel(exit_cols, "es", "missed_upside_pct"),
                reentry_window_summary=sel(exit_cols, "es", "reentry_window_summary"),
                canonical_exit_version=sel(exit_cols, "es", "canonical_exit_version"),
                canonical_exit_hash=sel(exit_cols, "es", "canonical_exit_hash"),
                entry_canonical_intelligence_hash=sel(exit_cols, "es", "entry_canonical_intelligence_hash"),
            ) if can_join_exit else """
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
            exit_join = ""
            if can_join_exit:
                exit_join = f"""
                LEFT JOIN exit_snapshots es
                  ON {' OR '.join(exit_join_terms)}
            """

            rejected_join_terms = []
            if has_rejected:
                if "decision_snapshot_id" in rejected_cols:
                    rejected_join_terms.append("rso.decision_snapshot_id = ds.id")
                if "trade_id" in rejected_cols and "trade_id" in decision_cols:
                    rejected_join_terms.append("rso.trade_id = ds.trade_id")
            can_join_rejected = has_rejected and bool(rejected_join_terms)

            rejected_select = """
                rso.id AS rejected_outcome_id,
                {label_status},
                {return_30m},
                {return_60m},
                {max_favorable_60m},
                {max_adverse_60m},
                {canonical_intelligence_hash}
            """.format(
                label_status=sel(rejected_cols, "rso", "label_status", "rejected_label_status"),
                return_30m=sel(rejected_cols, "rso", "return_30m", "rejected_return_30m"),
                return_60m=sel(rejected_cols, "rso", "return_60m", "rejected_return_60m"),
                max_favorable_60m=sel(
                    rejected_cols,
                    "rso",
                    "max_favorable_60m",
                    "rejected_max_favorable_60m",
                ),
                max_adverse_60m=sel(
                    rejected_cols,
                    "rso",
                    "max_adverse_60m",
                    "rejected_max_adverse_60m",
                ),
                canonical_intelligence_hash=sel(
                    rejected_cols,
                    "rso",
                    "canonical_intelligence_hash",
                    "rejected_canonical_intelligence_hash",
                ),
            ) if can_join_rejected else """
                NULL AS rejected_outcome_id,
                NULL AS rejected_label_status,
                NULL AS rejected_return_30m,
                NULL AS rejected_return_60m,
                NULL AS rejected_max_favorable_60m,
                NULL AS rejected_max_adverse_60m,
                NULL AS rejected_canonical_intelligence_hash
            """
            rejected_join = ""
            if can_join_rejected:
                rejected_join = f"""
                LEFT JOIN rejected_signal_outcomes rso
                  ON {' OR '.join(rejected_join_terms)}
            """

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
                    {sel(decision_cols, "ds", "canonical_intelligence_json")},
                    {sel(decision_cols, "ds", "canonical_intelligence_version", "entry_canonical_intelligence_version")},
                    {sel(decision_cols, "ds", "canonical_intelligence_hash", "entry_canonical_intelligence_hash")},
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
