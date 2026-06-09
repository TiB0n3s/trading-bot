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
        return (
            con.execute(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            is not None
        )

    @staticmethod
    def _table_columns(con, table: str) -> set[str]:
        if not LifecycleAnalysisRepository._table_exists(con, table):
            return set()
        return {row["name"] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}

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

            has_trades = self._table_exists(con, "trades")
            has_matched_trades = self._table_exists(con, "matched_trades")
            has_exit = self._table_exists(con, "exit_snapshots")
            has_rejected = self._table_exists(con, "rejected_signal_outcomes")
            decision_cols = self._table_columns(con, "decision_snapshots")
            trade_cols = self._table_columns(con, "trades")
            matched_cols = self._table_columns(con, "matched_trades")
            exit_cols = self._table_columns(con, "exit_snapshots")
            rejected_cols = self._table_columns(con, "rejected_signal_outcomes")
            sel = self._select

            can_join_trades = has_trades and "trade_id" in decision_cols and "id" in trade_cols
            trade_join = "LEFT JOIN trades t ON t.id = ds.trade_id" if can_join_trades else ""
            trade_select = """
                {order_status},
                {order_id},
                {fill_price},
                {qty}
            """.format(
                order_status=sel(trade_cols, "t", "order_status", "trade_order_status")
                if can_join_trades
                else "NULL AS trade_order_status",
                order_id=sel(trade_cols, "t", "order_id", "trade_order_id")
                if can_join_trades
                else "NULL AS trade_order_id",
                fill_price=sel(trade_cols, "t", "fill_price", "trade_fill_price")
                if can_join_trades
                else "NULL AS trade_fill_price",
                qty=sel(trade_cols, "t", "qty", "trade_qty")
                if can_join_trades
                else "NULL AS trade_qty",
            )
            historical_context_select = """
                {momentum_direction},
                {momentum_pct},
                {momentum_acceleration_pct},
                {momentum_state},
                {session_trend_label},
                {session_trend_score},
                {session_return_pct},
                {session_momentum_5m_pct},
                {session_momentum_15m_pct},
                {session_momentum_30m_pct},
                {session_momentum_60m_pct},
                {session_momentum_120m_pct},
                {session_distance_from_vwap_pct},
                {session_trend_regime},
                {prediction_score},
                {prediction_decision},
                {prediction_reason},
                {prediction_confidence},
                {prediction_sample_size},
                {setup_label},
                {setup_score},
                {setup_policy_action},
                {setup_policy_reason},
                {setup_confidence}
            """.format(
                momentum_direction=sel(decision_cols, "ds", "momentum_direction"),
                momentum_pct=sel(decision_cols, "ds", "momentum_pct"),
                momentum_acceleration_pct=sel(
                    decision_cols,
                    "ds",
                    "momentum_acceleration_pct",
                ),
                momentum_state=sel(decision_cols, "ds", "momentum_state"),
                session_trend_label=sel(decision_cols, "ds", "session_trend_label"),
                session_trend_score=sel(decision_cols, "ds", "session_trend_score"),
                session_return_pct=sel(decision_cols, "ds", "session_return_pct"),
                session_momentum_5m_pct=sel(
                    decision_cols,
                    "ds",
                    "session_momentum_5m_pct",
                ),
                session_momentum_15m_pct=sel(
                    decision_cols,
                    "ds",
                    "session_momentum_15m_pct",
                ),
                session_momentum_30m_pct=sel(
                    decision_cols,
                    "ds",
                    "session_momentum_30m_pct",
                ),
                session_momentum_60m_pct=sel(
                    decision_cols,
                    "ds",
                    "session_momentum_60m_pct",
                ),
                session_momentum_120m_pct=sel(
                    decision_cols,
                    "ds",
                    "session_momentum_120m_pct",
                ),
                session_distance_from_vwap_pct=sel(
                    decision_cols,
                    "ds",
                    "session_distance_from_vwap_pct",
                ),
                session_trend_regime=sel(decision_cols, "ds", "session_trend_regime"),
                prediction_score=sel(decision_cols, "ds", "prediction_score"),
                prediction_decision=sel(decision_cols, "ds", "prediction_decision"),
                prediction_reason=sel(decision_cols, "ds", "prediction_reason"),
                prediction_confidence=sel(decision_cols, "ds", "prediction_confidence"),
                prediction_sample_size=sel(
                    decision_cols,
                    "ds",
                    "prediction_sample_size",
                ),
                setup_label=sel(decision_cols, "ds", "setup_label"),
                setup_score=sel(decision_cols, "ds", "setup_score"),
                setup_policy_action=sel(decision_cols, "ds", "setup_policy_action"),
                setup_policy_reason=sel(decision_cols, "ds", "setup_policy_reason"),
                setup_confidence=sel(decision_cols, "ds", "setup_confidence"),
            )

            can_join_matched = (
                has_matched_trades
                and can_join_trades
                and "entry_order_id" in matched_cols
                and "order_id" in trade_cols
            )
            matched_join = ""
            if can_join_matched:
                matched_join = """
                LEFT JOIN (
                    SELECT
                        entry_order_id,
                        MAX(id) AS matched_trade_id,
                        COUNT(*) AS matched_exit_count,
                        MAX(exit_timestamp) AS matched_exit_timestamp,
                        SUM(COALESCE(realized_pnl, 0)) AS matched_realized_pnl,
                        MAX(exit_order_id) AS matched_exit_order_id,
                        MAX(realized_pnl_pct) AS matched_realized_return_pct,
                        MAX(mfe_pct) AS matched_mfe_pct,
                        MAX(capture_ratio) AS matched_capture_ratio
                    FROM matched_trades
                    WHERE entry_order_id IS NOT NULL
                    GROUP BY entry_order_id
                ) mt ON mt.entry_order_id = t.order_id
                """
            matched_select = """
                {matched_trade_id},
                {matched_exit_count},
                {matched_exit_timestamp},
                {matched_realized_pnl},
                {matched_exit_order_id}
            """.format(
                matched_trade_id="mt.matched_trade_id AS matched_trade_id"
                if can_join_matched
                else "NULL AS matched_trade_id",
                matched_exit_count="mt.matched_exit_count AS matched_exit_count"
                if can_join_matched
                else "NULL AS matched_exit_count",
                matched_exit_timestamp="mt.matched_exit_timestamp AS matched_exit_timestamp"
                if can_join_matched
                else "NULL AS matched_exit_timestamp",
                matched_realized_pnl="mt.matched_realized_pnl AS matched_realized_pnl"
                if can_join_matched
                else "NULL AS matched_realized_pnl",
                matched_exit_order_id="mt.matched_exit_order_id AS matched_exit_order_id"
                if can_join_matched
                else "NULL AS matched_exit_order_id",
            )

            exit_join_terms = []
            if has_exit:
                if "entry_trade_id" in exit_cols and "trade_id" in decision_cols:
                    exit_join_terms.append("es.entry_trade_id = ds.trade_id")
                if can_join_matched and "matched_trade_id" in exit_cols:
                    exit_join_terms.append("es.matched_trade_id = mt.matched_trade_id")
                if "decision_snapshot_id" in exit_cols:
                    exit_join_terms.append("es.decision_snapshot_id = ds.id")
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
            realized_return_select = sel(exit_cols, "es", "realized_return_pct")
            mfe_select = sel(exit_cols, "es", "mfe_pct")
            capture_select = sel(exit_cols, "es", "capture_ratio")
            if can_join_matched:
                realized_return_select = (
                    "COALESCE(es.realized_return_pct, mt.matched_realized_return_pct) "
                    "AS realized_return_pct"
                    if can_join_exit and "realized_return_pct" in exit_cols
                    else "mt.matched_realized_return_pct AS realized_return_pct"
                )
                mfe_select = (
                    "COALESCE(es.mfe_pct, mt.matched_mfe_pct) AS mfe_pct"
                    if can_join_exit and "mfe_pct" in exit_cols
                    else "mt.matched_mfe_pct AS mfe_pct"
                )
                capture_select = (
                    "COALESCE(es.capture_ratio, mt.matched_capture_ratio) AS capture_ratio"
                    if can_join_exit and "capture_ratio" in exit_cols
                    else "mt.matched_capture_ratio AS capture_ratio"
                )

            exit_select = (
                """
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
                    realized_return_pct=realized_return_select,
                    mfe_pct=mfe_select,
                    capture_ratio=capture_select,
                    max_adverse_excursion_pct=sel(exit_cols, "es", "max_adverse_excursion_pct"),
                    avoided_drawdown_pct=sel(exit_cols, "es", "avoided_drawdown_pct"),
                    missed_upside_pct=sel(exit_cols, "es", "missed_upside_pct"),
                    reentry_window_summary=sel(exit_cols, "es", "reentry_window_summary"),
                    canonical_exit_version=sel(exit_cols, "es", "canonical_exit_version"),
                    canonical_exit_hash=sel(exit_cols, "es", "canonical_exit_hash"),
                    entry_canonical_intelligence_hash=sel(
                        exit_cols, "es", "entry_canonical_intelligence_hash"
                    ),
                )
                if can_join_exit
                else f"""
                NULL AS exit_snapshot_id,
                NULL AS exit_timestamp,
                NULL AS exit_trigger,
                NULL AS exit_source,
                NULL AS realized_pnl,
                {realized_return_select if can_join_matched else "NULL AS realized_return_pct"},
                {mfe_select if can_join_matched else "NULL AS mfe_pct"},
                {capture_select if can_join_matched else "NULL AS capture_ratio"},
                NULL AS max_adverse_excursion_pct,
                NULL AS avoided_drawdown_pct,
                NULL AS missed_upside_pct,
                NULL AS reentry_window_summary,
                NULL AS canonical_exit_version,
                NULL AS canonical_exit_hash,
                NULL AS entry_canonical_intelligence_hash
            """
            )
            exit_join = ""
            if can_join_exit:
                exit_join = f"""
                LEFT JOIN exit_snapshots es
                  ON {" OR ".join(exit_join_terms)}
            """

            rejected_join_terms = []
            if has_rejected:
                if "decision_snapshot_id" in rejected_cols:
                    rejected_join_terms.append("rso.decision_snapshot_id = ds.id")
                if "trade_id" in rejected_cols and "trade_id" in decision_cols:
                    rejected_join_terms.append("rso.trade_id = ds.trade_id")
            can_join_rejected = has_rejected and bool(rejected_join_terms)

            rejected_select = (
                """
                rso.id AS rejected_outcome_id,
                {label_status},
                {return_30m},
                {return_60m},
                {return_eod},
                {max_favorable_60m},
                {max_adverse_60m},
                {canonical_intelligence_hash}
            """.format(
                    label_status=sel(rejected_cols, "rso", "label_status", "rejected_label_status"),
                    return_30m=sel(rejected_cols, "rso", "return_30m", "rejected_return_30m"),
                    return_60m=sel(rejected_cols, "rso", "return_60m", "rejected_return_60m"),
                    return_eod=sel(rejected_cols, "rso", "return_eod", "rejected_return_eod"),
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
                )
                if can_join_rejected
                else """
                NULL AS rejected_outcome_id,
                NULL AS rejected_label_status,
                NULL AS rejected_return_30m,
                NULL AS rejected_return_60m,
                NULL AS rejected_return_eod,
                NULL AS rejected_max_favorable_60m,
                NULL AS rejected_max_adverse_60m,
                NULL AS rejected_canonical_intelligence_hash
            """
            )
            rejected_join = ""
            if can_join_rejected:
                rejected_join = f"""
                LEFT JOIN rejected_signal_outcomes rso
                  ON {" OR ".join(rejected_join_terms)}
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
                    {trade_select},
                    {matched_select},
                    {sel(decision_cols, "ds", "canonical_intelligence_json")},
                    {sel(decision_cols, "ds", "canonical_intelligence_version", "entry_canonical_intelligence_version")},
                    {sel(decision_cols, "ds", "canonical_intelligence_hash", "entry_canonical_intelligence_hash")},
                    {historical_context_select},
                    {exit_select},
                    {rejected_select}
                FROM decision_snapshots ds
                {trade_join}
                {matched_join}
                {exit_join}
                {rejected_join}
                WHERE {" AND ".join(clauses)}
                ORDER BY ds.decision_time ASC, ds.id ASC
                {limit_sql}
                """,
                params,
            ).fetchall()

    def approved_trade_rows_without_snapshots(
        self,
        *,
        start_date: str,
        end_date: str,
        symbol: str | None = None,
    ) -> list[Any]:
        """Approved trade rows that predate or bypass decision snapshot capture."""
        with get_connection(self.db_path) as con:
            if not self._table_exists(con, "trades"):
                return []

            trade_cols = self._table_columns(con, "trades")
            matched_cols = self._table_columns(con, "matched_trades")
            exit_cols = self._table_columns(con, "exit_snapshots")
            decision_cols = self._table_columns(con, "decision_snapshots")
            sel = self._select

            if "timestamp" not in trade_cols or "action" not in trade_cols:
                return []

            decision_join = ""
            decision_absent_clause = "1=1"
            if (
                self._table_exists(con, "decision_snapshots")
                and "trade_id" in decision_cols
                and "id" in trade_cols
            ):
                decision_join = "LEFT JOIN decision_snapshots ds ON ds.trade_id = t.id"
                decision_absent_clause = "ds.id IS NULL"
            candidate_join = ""
            candidate_json_select = "NULL AS candidate_json"
            if self._table_exists(con, "candidate_universe"):
                candidate_cols = self._table_columns(con, "candidate_universe")
                if {
                    "symbol",
                    "candidate_ts",
                    "candidate_status",
                    "candidate_json",
                } <= candidate_cols:
                    candidate_join = """
                    LEFT JOIN candidate_universe cu
                      ON UPPER(cu.symbol) = UPPER(t.symbol)
                     AND cu.candidate_status = 'taken'
                     AND replace(substr(cu.candidate_ts, 1, 19), 'T', ' ') = t.timestamp
                    """
                    candidate_json_select = "cu.candidate_json AS candidate_json"

            can_join_matched = (
                self._table_exists(con, "matched_trades")
                and "entry_order_id" in matched_cols
                and "order_id" in trade_cols
            )
            matched_join = ""
            if can_join_matched:
                matched_join = """
                LEFT JOIN (
                    SELECT
                        entry_order_id,
                        MAX(id) AS matched_trade_id,
                        COUNT(*) AS matched_exit_count,
                        MAX(exit_timestamp) AS matched_exit_timestamp,
                        SUM(COALESCE(realized_pnl, 0)) AS matched_realized_pnl,
                        MAX(exit_order_id) AS matched_exit_order_id,
                        MAX(realized_pnl_pct) AS matched_realized_return_pct,
                        MAX(mfe_pct) AS matched_mfe_pct,
                        MAX(capture_ratio) AS matched_capture_ratio,
                        MAX(exit_reason) AS matched_exit_reason
                    FROM matched_trades
                    WHERE entry_order_id IS NOT NULL
                    GROUP BY entry_order_id
                ) mt ON mt.entry_order_id = t.order_id
                """
            can_join_direct_exit = {
                "id",
                "timestamp",
                "symbol",
                "action",
                "fill_price",
                "qty",
            } <= trade_cols
            direct_exit_join = ""
            if can_join_direct_exit:
                direct_exit_join = """
                LEFT JOIN (
                    SELECT
                        b.id AS entry_trade_id,
                        COUNT(s.id) AS direct_exit_count,
                        MAX(s.timestamp) AS direct_exit_timestamp,
                        SUM((s.fill_price - b.fill_price) * s.qty) AS direct_realized_pnl,
                        ROUND(
                            SUM(((s.fill_price - b.fill_price) / b.fill_price * 100.0) * s.qty)
                            / NULLIF(SUM(s.qty), 0),
                            4
                        ) AS direct_realized_return_pct,
                        MAX(s.rejection_reason) AS direct_exit_reason
                    FROM trades b
                    JOIN trades s
                      ON UPPER(s.symbol) = UPPER(b.symbol)
                     AND LOWER(COALESCE(s.action, '')) = 'sell'
                     AND COALESCE(s.approved, 0) = 1
                     AND s.timestamp > b.timestamp
                     AND s.timestamp < COALESCE(
                        (
                            SELECT MIN(nb.timestamp)
                            FROM trades nb
                            WHERE UPPER(nb.symbol) = UPPER(b.symbol)
                              AND LOWER(COALESCE(nb.action, '')) = 'buy'
                              AND COALESCE(nb.approved, 0) = 1
                              AND nb.timestamp > b.timestamp
                        ),
                        '9999-12-31'
                     )
                    WHERE LOWER(COALESCE(b.action, '')) = 'buy'
                      AND COALESCE(b.approved, 0) = 1
                      AND b.fill_price IS NOT NULL
                      AND b.fill_price > 0
                    GROUP BY b.id
                ) dx ON dx.entry_trade_id = t.id
                """

            can_join_exit_by_trade = (
                self._table_exists(con, "exit_snapshots")
                and "entry_trade_id" in exit_cols
                and "id" in trade_cols
            )
            exit_join_terms = []
            if can_join_exit_by_trade:
                exit_join_terms.append("es.entry_trade_id = t.id")
            if (
                self._table_exists(con, "exit_snapshots")
                and can_join_matched
                and "matched_trade_id" in exit_cols
            ):
                exit_join_terms.append("es.matched_trade_id = mt.matched_trade_id")
            exit_join = ""
            if exit_join_terms:
                exit_join = f"LEFT JOIN exit_snapshots es ON {' OR '.join(exit_join_terms)}"

            clauses = [
                "substr(t.timestamp, 1, 10) BETWEEN ? AND ?",
                "LOWER(COALESCE(t.action, '')) = 'buy'",
                "COALESCE(t.approved, 0) = 1",
                decision_absent_clause,
            ]
            params: list[Any] = [start_date, end_date]
            if symbol:
                clauses.append("UPPER(t.symbol) = ?")
                params.append(symbol.upper())

            realized_return_pct = (
                "COALESCE(es.realized_return_pct, mt.matched_realized_return_pct, dx.direct_realized_return_pct) AS realized_return_pct"
                if exit_join_terms and can_join_matched and can_join_direct_exit
                else "COALESCE(es.realized_return_pct, mt.matched_realized_return_pct) AS realized_return_pct"
                if exit_join_terms and can_join_matched
                else "COALESCE(es.realized_return_pct, dx.direct_realized_return_pct) AS realized_return_pct"
                if exit_join_terms and can_join_direct_exit
                else "COALESCE(mt.matched_realized_return_pct, dx.direct_realized_return_pct) AS realized_return_pct"
                if can_join_matched and can_join_direct_exit
                else (
                    "es.realized_return_pct AS realized_return_pct"
                    if exit_join_terms
                    else (
                        "mt.matched_realized_return_pct AS realized_return_pct"
                        if can_join_matched
                        else (
                            "dx.direct_realized_return_pct AS realized_return_pct"
                            if can_join_direct_exit
                            else "NULL AS realized_return_pct"
                        )
                    )
                )
            )
            mfe_pct = (
                "COALESCE(es.mfe_pct, mt.matched_mfe_pct) AS mfe_pct"
                if exit_join_terms and can_join_matched
                else (
                    "es.mfe_pct AS mfe_pct"
                    if exit_join_terms
                    else (
                        "mt.matched_mfe_pct AS mfe_pct" if can_join_matched else "NULL AS mfe_pct"
                    )
                )
            )
            capture_ratio = (
                "COALESCE(es.capture_ratio, mt.matched_capture_ratio) AS capture_ratio"
                if exit_join_terms and can_join_matched
                else (
                    "es.capture_ratio AS capture_ratio"
                    if exit_join_terms
                    else (
                        "mt.matched_capture_ratio AS capture_ratio"
                        if can_join_matched
                        else "NULL AS capture_ratio"
                    )
                )
            )
            exit_trigger = (
                "COALESCE(es.exit_trigger, mt.matched_exit_reason, dx.direct_exit_reason) AS exit_trigger"
                if exit_join_terms and can_join_matched and can_join_direct_exit
                else "COALESCE(es.exit_trigger, mt.matched_exit_reason) AS exit_trigger"
                if exit_join_terms and can_join_matched
                else "COALESCE(es.exit_trigger, dx.direct_exit_reason) AS exit_trigger"
                if exit_join_terms and can_join_direct_exit
                else "COALESCE(mt.matched_exit_reason, dx.direct_exit_reason) AS exit_trigger"
                if can_join_matched and can_join_direct_exit
                else (
                    "es.exit_trigger AS exit_trigger"
                    if exit_join_terms
                    else (
                        "mt.matched_exit_reason AS exit_trigger"
                        if can_join_matched
                        else (
                            "dx.direct_exit_reason AS exit_trigger"
                            if can_join_direct_exit
                            else "NULL AS exit_trigger"
                        )
                    )
                )
            )
            matched_trade_id_select = (
                "COALESCE(mt.matched_trade_id, dx.entry_trade_id) AS matched_trade_id"
                if can_join_matched and can_join_direct_exit
                else "mt.matched_trade_id AS matched_trade_id"
                if can_join_matched
                else "dx.entry_trade_id AS matched_trade_id"
                if can_join_direct_exit
                else "NULL AS matched_trade_id"
            )
            matched_exit_count_select = (
                "COALESCE(mt.matched_exit_count, dx.direct_exit_count) AS matched_exit_count"
                if can_join_matched and can_join_direct_exit
                else "mt.matched_exit_count AS matched_exit_count"
                if can_join_matched
                else "dx.direct_exit_count AS matched_exit_count"
                if can_join_direct_exit
                else "NULL AS matched_exit_count"
            )
            matched_exit_timestamp_select = (
                "COALESCE(mt.matched_exit_timestamp, dx.direct_exit_timestamp) AS matched_exit_timestamp"
                if can_join_matched and can_join_direct_exit
                else "mt.matched_exit_timestamp AS matched_exit_timestamp"
                if can_join_matched
                else "dx.direct_exit_timestamp AS matched_exit_timestamp"
                if can_join_direct_exit
                else "NULL AS matched_exit_timestamp"
            )
            matched_realized_pnl_select = (
                "COALESCE(mt.matched_realized_pnl, dx.direct_realized_pnl) AS matched_realized_pnl"
                if can_join_matched and can_join_direct_exit
                else "mt.matched_realized_pnl AS matched_realized_pnl"
                if can_join_matched
                else "dx.direct_realized_pnl AS matched_realized_pnl"
                if can_join_direct_exit
                else "NULL AS matched_realized_pnl"
            )
            matched_exit_order_id_select = (
                "mt.matched_exit_order_id AS matched_exit_order_id"
                if can_join_matched
                else "NULL AS matched_exit_order_id"
            )
            exit_timestamp_select = (
                "COALESCE(es.exit_timestamp, mt.matched_exit_timestamp, dx.direct_exit_timestamp) AS exit_timestamp"
                if exit_join_terms and can_join_matched and can_join_direct_exit
                else "COALESCE(es.exit_timestamp, mt.matched_exit_timestamp) AS exit_timestamp"
                if exit_join_terms and can_join_matched
                else "COALESCE(es.exit_timestamp, dx.direct_exit_timestamp) AS exit_timestamp"
                if exit_join_terms and can_join_direct_exit
                else "COALESCE(mt.matched_exit_timestamp, dx.direct_exit_timestamp) AS exit_timestamp"
                if can_join_matched and can_join_direct_exit
                else "es.exit_timestamp AS exit_timestamp"
                if exit_join_terms
                else "mt.matched_exit_timestamp AS exit_timestamp"
                if can_join_matched
                else "dx.direct_exit_timestamp AS exit_timestamp"
                if can_join_direct_exit
                else "NULL AS exit_timestamp"
            )
            realized_pnl_select = (
                "COALESCE(es.realized_pnl, mt.matched_realized_pnl, dx.direct_realized_pnl) AS realized_pnl"
                if exit_join_terms and can_join_matched and can_join_direct_exit
                else "COALESCE(es.realized_pnl, mt.matched_realized_pnl) AS realized_pnl"
                if exit_join_terms and can_join_matched
                else "COALESCE(es.realized_pnl, dx.direct_realized_pnl) AS realized_pnl"
                if exit_join_terms and can_join_direct_exit
                else "COALESCE(mt.matched_realized_pnl, dx.direct_realized_pnl) AS realized_pnl"
                if can_join_matched and can_join_direct_exit
                else "es.realized_pnl AS realized_pnl"
                if exit_join_terms
                else "mt.matched_realized_pnl AS realized_pnl"
                if can_join_matched
                else "dx.direct_realized_pnl AS realized_pnl"
                if can_join_direct_exit
                else "NULL AS realized_pnl"
            )

            return con.execute(
                f"""
                SELECT
                    NULL AS decision_snapshot_id,
                    t.id AS trade_id,
                    t.timestamp AS decision_time,
                    t.symbol,
                    t.action,
                    t.approved,
                    'approved' AS final_decision,
                    t.rejection_reason,
                    {sel(trade_cols, "t", "order_status", "trade_order_status")},
                    {sel(trade_cols, "t", "order_id", "trade_order_id")},
                    {sel(trade_cols, "t", "fill_price", "trade_fill_price")},
                    {sel(trade_cols, "t", "qty", "trade_qty")},
                    {matched_trade_id_select},
                    {matched_exit_count_select},
                    {matched_exit_timestamp_select},
                    {matched_realized_pnl_select},
                    {matched_exit_order_id_select},
                    NULL AS canonical_intelligence_json,
                    {candidate_json_select},
                    NULL AS entry_canonical_intelligence_version,
                    NULL AS entry_canonical_intelligence_hash,
                    {sel(trade_cols, "t", "momentum_direction")},
                    {sel(trade_cols, "t", "momentum_pct")},
                    NULL AS momentum_acceleration_pct,
                    NULL AS momentum_state,
                    {sel(trade_cols, "t", "session_trend_label")},
                    {sel(trade_cols, "t", "session_trend_score")},
                    {sel(trade_cols, "t", "session_return_pct")},
                    {sel(trade_cols, "t", "session_momentum_5m_pct")},
                    {sel(trade_cols, "t", "session_momentum_15m_pct")},
                    {sel(trade_cols, "t", "session_momentum_30m_pct")},
                    NULL AS session_momentum_60m_pct,
                    NULL AS session_momentum_120m_pct,
                    {sel(trade_cols, "t", "session_distance_from_vwap_pct")},
                    NULL AS session_trend_regime,
                    {sel(trade_cols, "t", "prediction_score")},
                    {sel(trade_cols, "t", "prediction_decision")},
                    {sel(trade_cols, "t", "prediction_reason")},
                    NULL AS prediction_confidence,
                    NULL AS prediction_sample_size,
                    {sel(trade_cols, "t", "setup_label")},
                    {sel(trade_cols, "t", "setup_policy_action")},
                    {sel(trade_cols, "t", "setup_policy_reason")},
                    NULL AS setup_confidence,
                    {("es.id AS exit_snapshot_id" if exit_join_terms else "NULL AS exit_snapshot_id")},
                    {exit_timestamp_select},
                    {exit_trigger},
                    {("es.exit_source AS exit_source" if exit_join_terms else "NULL AS exit_source")},
                    {realized_pnl_select},
                    {realized_return_pct},
                    {mfe_pct},
                    {capture_ratio},
                    {("es.max_adverse_excursion_pct AS max_adverse_excursion_pct" if exit_join_terms else "NULL AS max_adverse_excursion_pct")},
                    {("es.avoided_drawdown_pct AS avoided_drawdown_pct" if exit_join_terms else "NULL AS avoided_drawdown_pct")},
                    {("es.missed_upside_pct AS missed_upside_pct" if exit_join_terms else "NULL AS missed_upside_pct")},
                    {("es.reentry_window_summary AS reentry_window_summary" if exit_join_terms else "NULL AS reentry_window_summary")},
                    {("es.canonical_exit_version AS canonical_exit_version" if exit_join_terms else "NULL AS canonical_exit_version")},
                    {("es.canonical_exit_hash AS canonical_exit_hash" if exit_join_terms else "NULL AS canonical_exit_hash")},
                    {("es.entry_canonical_intelligence_hash AS entry_canonical_intelligence_hash" if exit_join_terms else "NULL AS entry_canonical_intelligence_hash")},
                    NULL AS rejected_outcome_id,
                    NULL AS rejected_label_status,
                    NULL AS rejected_return_30m,
                    NULL AS rejected_return_60m,
                    NULL AS rejected_return_eod,
                    NULL AS rejected_max_favorable_60m,
                    NULL AS rejected_max_adverse_60m,
                    NULL AS rejected_canonical_intelligence_hash
                FROM trades t
                {decision_join}
                {candidate_join}
                {matched_join}
                {direct_exit_join}
                {exit_join}
                WHERE {" AND ".join(clauses)}
                ORDER BY t.timestamp ASC, t.id ASC
                """,
                params,
            ).fetchall()
