"""Repository boundary for canonical exit snapshots."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from db import DB_PATH, get_connection


class ExitSnapshotRepository:
    def __init__(self, db_path: Path | str | None = None):
        self.db_path = db_path or DB_PATH

    def init_table(self) -> None:
        with get_connection(self.db_path) as con:
            con.execute(
                """
                CREATE TABLE IF NOT EXISTS exit_snapshots (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    created_at TEXT NOT NULL,
                    decision_snapshot_id INTEGER,
                    entry_trade_id INTEGER,
                    exit_trade_id INTEGER,
                    matched_trade_id INTEGER,
                    position_id TEXT,
                    symbol TEXT,
                    exit_timestamp TEXT,
                    exit_trigger TEXT,
                    exit_source TEXT,
                    realized_pnl REAL,
                    realized_return_pct REAL,
                    mfe_pct REAL,
                    capture_ratio REAL,
                    max_adverse_excursion_pct REAL,
                    avoided_drawdown_pct REAL,
                    missed_upside_pct REAL,
                    post_exit_return_30m_pct REAL,
                    post_exit_return_60m_pct REAL,
                    reentry_window_summary TEXT,
                    exit_regime_state_json TEXT,
                    exit_momentum_state_json TEXT,
                    exit_trend_state_json TEXT,
                    canonical_exit_version TEXT NOT NULL,
                    canonical_exit_hash TEXT NOT NULL,
                    canonical_exit_json TEXT NOT NULL,
                    canonical_intelligence_hash TEXT,
                    entry_canonical_intelligence_version TEXT,
                    entry_canonical_intelligence_hash TEXT
                )
                """
            )
            existing_cols = {
                row["name"] for row in con.execute("PRAGMA table_info(exit_snapshots)").fetchall()
            }
            addable = {
                "decision_snapshot_id": "INTEGER",
                "entry_trade_id": "INTEGER",
                "position_id": "TEXT",
                "max_adverse_excursion_pct": "REAL",
                "reentry_window_summary": "TEXT",
                "exit_regime_state_json": "TEXT",
                "exit_momentum_state_json": "TEXT",
                "exit_trend_state_json": "TEXT",
                "entry_canonical_intelligence_version": "TEXT",
                "entry_canonical_intelligence_hash": "TEXT",
            }
            for col, col_type in addable.items():
                if col not in existing_cols:
                    con.execute(f"ALTER TABLE exit_snapshots ADD COLUMN {col} {col_type}")
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_exit_snapshots_symbol_time
                ON exit_snapshots(symbol, exit_timestamp)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_exit_snapshots_trade
                ON exit_snapshots(exit_trade_id, matched_trade_id)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_exit_snapshots_decision
                ON exit_snapshots(decision_snapshot_id)
                """
            )
            con.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_exit_snapshots_entry_hash
                ON exit_snapshots(entry_canonical_intelligence_hash)
                """
            )

    def insert_snapshot(self, row: dict[str, Any]) -> int:
        self.init_table()
        columns = list(row.keys())
        placeholders = ", ".join(["?"] * len(columns))
        with get_connection(self.db_path) as con:
            cur = con.execute(
                f"INSERT INTO exit_snapshots ({', '.join(columns)}) VALUES ({placeholders})",
                [row[col] for col in columns],
            )
            return int(cur.lastrowid)

    @staticmethod
    def _table_exists(con: Any, table: str) -> bool:
        row = con.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name=?",
            (table,),
        ).fetchone()
        return row is not None

    @classmethod
    def _table_columns(cls, con: Any, table: str) -> set[str]:
        if not cls._table_exists(con, table):
            return set()
        return {str(row["name"]) for row in con.execute(f"PRAGMA table_info({table})")}

    def approved_matched_exit_rows_missing_snapshots(
        self,
        *,
        start_date: str,
        end_date: str | None = None,
        limit: int | None = None,
    ):
        """Return approved BUY entries with matched exits but no exit snapshot.

        Historical matching can produce multiple rows for partial exits. For
        the lifecycle-level repair path, use the latest matched exit per entry
        order so one approved entry maps to one canonical exit snapshot.
        """
        self.init_table()
        end_date = end_date or start_date
        limit_sql = "LIMIT ?" if limit else ""
        params: list[Any] = [start_date, end_date]
        if limit:
            params.append(limit)

        with get_connection(self.db_path) as con:
            return con.execute(
                f"""
                WITH latest_match AS (
                    SELECT entry_order_id, MAX(id) AS matched_trade_id
                    FROM matched_trades
                    WHERE entry_order_id IS NOT NULL
                    GROUP BY entry_order_id
                )
                SELECT
                    ds.id AS decision_snapshot_id,
                    ds.decision_time AS decision_time,
                    ds.trade_id AS entry_trade_id,
                    ds.symbol AS symbol,
                    ds.canonical_intelligence_version AS entry_canonical_intelligence_version,
                    ds.canonical_intelligence_hash AS entry_canonical_intelligence_hash,
                    ds.canonical_intelligence_json AS canonical_intelligence_json,
                    t.order_id AS entry_order_id,
                    t.qty AS entry_qty,
                    t.fill_price AS entry_fill_price,
                    mt.id AS matched_trade_id,
                    mt.exit_order_id AS exit_order_id,
                    mt.exit_timestamp AS exit_timestamp,
                    mt.exit_reason AS exit_reason,
                    mt.holding_minutes AS holding_minutes,
                    mt.qty AS exit_qty,
                    mt.entry_price AS matched_entry_price,
                    mt.exit_price AS exit_price,
                    mt.realized_pnl AS realized_pnl,
                    mt.realized_pnl_pct AS realized_return_pct,
                    mt.mfe_pct AS mfe_pct,
                    mt.capture_ratio AS capture_ratio
                FROM decision_snapshots ds
                JOIN trades t
                  ON t.id = ds.trade_id
                JOIN latest_match lm
                  ON lm.entry_order_id = t.order_id
                JOIN matched_trades mt
                  ON mt.id = lm.matched_trade_id
                LEFT JOIN exit_snapshots es
                  ON es.decision_snapshot_id = ds.id
                  OR es.matched_trade_id = mt.id
                  OR es.entry_trade_id = ds.trade_id
                WHERE ds.approved = 1
                  AND lower(COALESCE(ds.action, '')) = 'buy'
                  AND mt.exit_timestamp IS NOT NULL
                  AND es.id IS NULL
                  AND date(ds.decision_time) BETWEEN ? AND ?
                ORDER BY ds.decision_time, ds.id
                {limit_sql}
                """,
                params,
            ).fetchall()

    def latest_for_symbol(self, symbol: str, limit: int = 20):
        self.init_table()
        with get_connection(self.db_path) as con:
            return con.execute(
                """
                SELECT *
                FROM exit_snapshots
                WHERE symbol = ?
                ORDER BY exit_timestamp DESC, id DESC
                LIMIT ?
                """,
                (symbol, limit),
            ).fetchall()

    def approved_trade_rows_missing_snapshots(
        self,
        *,
        start_date: str,
        end_date: str | None = None,
        limit: int | None = None,
    ) -> list[dict[str, Any]]:
        """Return approved BUY trade rows with matched exits but no exit snapshot.

        This covers older/execution-bridge rows that were written to ``trades``
        without a corresponding canonical decision snapshot.
        """
        self.init_table()
        end_date = end_date or start_date
        with get_connection(self.db_path) as con:
            trade_cols = self._table_columns(con, "trades")
            matched_cols = self._table_columns(con, "matched_trades")
            exit_cols = self._table_columns(con, "exit_snapshots")
            decision_cols = self._table_columns(con, "decision_snapshots")
            required_trade = {
                "id",
                "timestamp",
                "symbol",
                "action",
                "approved",
                "order_id",
            }
            required_matched = {
                "id",
                "entry_order_id",
                "exit_timestamp",
            }
            if not required_trade <= trade_cols or not required_matched <= matched_cols:
                return []
            if not {"entry_trade_id", "matched_trade_id"} <= exit_cols:
                return []

            decision_join = ""
            decision_absent = "1 = 1"
            if {"id", "trade_id"} <= decision_cols:
                decision_join = "LEFT JOIN decision_snapshots ds ON ds.trade_id = t.id"
                decision_absent = "ds.id IS NULL"

            limit_sql = "LIMIT ?" if limit is not None else ""
            params: list[Any] = [start_date, end_date]
            if limit is not None:
                params.append(max(0, int(limit)))

            def matched_col(name: str, alias: str = "mt") -> str:
                return f"{alias}.{name}" if name in matched_cols else "NULL"

            rows = con.execute(
                f"""
                WITH latest_match AS (
                    SELECT entry_order_id, MAX(id) AS matched_trade_id
                    FROM matched_trades
                    WHERE entry_order_id IS NOT NULL
                    GROUP BY entry_order_id
                )
                SELECT
                    NULL AS decision_snapshot_id,
                    t.id AS trade_id,
                    t.id AS entry_trade_id,
                    t.timestamp AS decision_time,
                    t.symbol AS symbol,
                    t.order_id AS trade_order_id,
                    {("t.qty" if "qty" in trade_cols else "NULL")} AS trade_qty,
                    {("t.fill_price" if "fill_price" in trade_cols else "NULL")} AS trade_fill_price,
                    mt.id AS matched_trade_id,
                    {matched_col("exit_order_id")} AS matched_exit_order_id,
                    mt.exit_timestamp AS exit_timestamp,
                    {matched_col("exit_reason")} AS exit_reason,
                    {matched_col("holding_minutes")} AS holding_minutes,
                    {matched_col("qty")} AS exit_qty,
                    {matched_col("entry_price")} AS matched_entry_price,
                    {matched_col("exit_price")} AS exit_price,
                    {matched_col("realized_pnl")} AS realized_pnl,
                    {matched_col("realized_pnl_pct")} AS realized_return_pct,
                    {matched_col("mfe_pct")} AS mfe_pct,
                    {matched_col("capture_ratio")} AS capture_ratio,
                    NULL AS canonical_intelligence_json,
                    NULL AS entry_canonical_intelligence_version,
                    NULL AS entry_canonical_intelligence_hash
                FROM trades t
                JOIN latest_match lm
                  ON lm.entry_order_id = t.order_id
                JOIN matched_trades mt
                  ON mt.id = lm.matched_trade_id
                {decision_join}
                LEFT JOIN exit_snapshots es
                  ON es.entry_trade_id = t.id
                  OR es.matched_trade_id = mt.id
                WHERE substr(t.timestamp, 1, 10) BETWEEN ? AND ?
                  AND LOWER(COALESCE(t.action, '')) = 'buy'
                  AND COALESCE(t.approved, 0) = 1
                  AND mt.exit_timestamp IS NOT NULL
                  AND es.id IS NULL
                  AND {decision_absent}
                ORDER BY t.timestamp ASC, t.id ASC
                {limit_sql}
                """,
                params,
            ).fetchall()
            return [dict(row) for row in rows]

    def exit_intelligence_summary(
        self,
        *,
        start_date: str,
        end_date: str | None = None,
        limit: int = 12,
    ) -> dict[str, Any]:
        self.init_table()
        end_date = end_date or start_date
        with get_connection(self.db_path) as con:
            summary = con.execute(
                """
                SELECT
                    COUNT(*) AS rows,
                    AVG(realized_return_pct) AS avg_realized_return_pct,
                    AVG(mfe_pct) AS avg_mfe_pct,
                    AVG(capture_ratio) AS avg_capture_ratio,
                    AVG(avoided_drawdown_pct) AS avg_avoided_drawdown_pct,
                    AVG(missed_upside_pct) AS avg_missed_upside_pct,
                    AVG(post_exit_return_30m_pct) AS avg_post_exit_return_30m_pct,
                    AVG(post_exit_return_60m_pct) AS avg_post_exit_return_60m_pct,
                    SUM(CASE WHEN missed_upside_pct >= 1.0 THEN 1 ELSE 0 END) AS high_missed_upside_count,
                    SUM(CASE WHEN post_exit_return_30m_pct > 0.5 THEN 1 ELSE 0 END) AS post_exit_recovery_count,
                    SUM(CASE WHEN avoided_drawdown_pct > 0.5 THEN 1 ELSE 0 END) AS avoided_drawdown_count
                FROM exit_snapshots
                WHERE date(exit_timestamp) BETWEEN ? AND ?
                """,
                (start_date, end_date),
            ).fetchone()
            trigger_rows = con.execute(
                """
                SELECT
                    COALESCE(exit_trigger, 'unknown') AS exit_trigger,
                    COUNT(*) AS rows,
                    AVG(realized_return_pct) AS avg_realized_return_pct,
                    AVG(capture_ratio) AS avg_capture_ratio,
                    AVG(missed_upside_pct) AS avg_missed_upside_pct,
                    AVG(post_exit_return_30m_pct) AS avg_post_exit_return_30m_pct
                FROM exit_snapshots
                WHERE date(exit_timestamp) BETWEEN ? AND ?
                GROUP BY COALESCE(exit_trigger, 'unknown')
                ORDER BY rows DESC, exit_trigger
                LIMIT ?
                """,
                (start_date, end_date, int(limit)),
            ).fetchall()
            symbol_rows = con.execute(
                """
                SELECT
                    COALESCE(symbol, 'unknown') AS symbol,
                    COUNT(*) AS rows,
                    AVG(realized_return_pct) AS avg_realized_return_pct,
                    AVG(capture_ratio) AS avg_capture_ratio,
                    AVG(missed_upside_pct) AS avg_missed_upside_pct
                FROM exit_snapshots
                WHERE date(exit_timestamp) BETWEEN ? AND ?
                GROUP BY COALESCE(symbol, 'unknown')
                ORDER BY rows DESC, symbol
                LIMIT ?
                """,
                (start_date, end_date, int(limit)),
            ).fetchall()
            matched_exit_total = con.execute(
                """
                SELECT COUNT(*) AS rows
                FROM matched_trades
                WHERE exit_timestamp IS NOT NULL
                  AND date(exit_timestamp) BETWEEN ? AND ?
                """,
                (start_date, end_date),
            ).fetchone()
        repairable_missing = self.approved_matched_exit_rows_missing_snapshots(
            start_date=start_date,
            end_date=end_date,
            limit=None,
        )
        return {
            "summary": dict(summary) if summary else {},
            "trigger_rows": [dict(row) for row in trigger_rows],
            "symbol_rows": [dict(row) for row in symbol_rows],
            "matched_exit_total": int(matched_exit_total["rows"] or 0) if matched_exit_total else 0,
            "repairable_missing_exit_snapshots": len(repairable_missing),
        }
