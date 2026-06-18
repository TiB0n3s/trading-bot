"""Repository boundary for research export table reads."""

from __future__ import annotations

from pathlib import Path
from typing import Any, Iterable, Iterator

from db import DB_PATH, get_connection


class ResearchExportRepository:
    """Read daily research datasets without leaking SQLite access to scripts."""

    def __init__(self, db_path: Path | str | None = None):
        self.db_path = db_path or DB_PATH

    @staticmethod
    def _valid_identifier(name: str) -> bool:
        return bool(name) and all(ch.isalnum() or ch == "_" for ch in name)

    def table_exists(self, table: str) -> bool:
        if not self._valid_identifier(table):
            return False
        with get_connection(self.db_path) as con:
            return (
                con.execute(
                    "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
                    (table,),
                ).fetchone()
                is not None
            )

    def table_columns(self, table: str) -> set[str]:
        if not self._valid_identifier(table) or not self.table_exists(table):
            return set()
        with get_connection(self.db_path) as con:
            return {row["name"] for row in con.execute(f"PRAGMA table_info({table})").fetchall()}

    @staticmethod
    def _quote_identifier(name: str) -> str:
        if not ResearchExportRepository._valid_identifier(name):
            raise ValueError(f"invalid SQLite identifier: {name!r}")
        return '"' + name.replace('"', '""') + '"'

    def iter_rows_for_date(
        self,
        *,
        table: str,
        target_date: str,
        date_columns: Iterable[str],
        limit: int | None = None,
        chunk_size: int = 1000,
    ) -> tuple[Iterator[tuple[list[dict[str, Any]], list[str]]], list[str]]:
        """Yield matching rows in bounded rowid pages.

        The export path intentionally avoids ``SELECT *`` and broad
        ``fetchall()`` calls because production ``trades.db`` can be large.
        """
        if not self._valid_identifier(table) or not self.table_exists(table):
            return iter(()), []

        columns = self.table_columns(table)
        usable_date_columns = [
            col for col in date_columns if self._valid_identifier(col) and col in columns
        ]
        if not usable_date_columns:
            return iter(()), []

        quoted_table = self._quote_identifier(table)
        ordered_columns = sorted(columns)
        select_columns = ", ".join(self._quote_identifier(col) for col in ordered_columns)
        where = " OR ".join(
            f"substr({self._quote_identifier(col)}, 1, 10) = ?" for col in usable_date_columns
        )
        date_params: list[Any] = [target_date] * len(usable_date_columns)
        page_size = max(1, int(chunk_size))
        remaining = int(limit) if limit is not None and limit > 0 else None

        def _iterator() -> Iterator[tuple[list[dict[str, Any]], list[str]]]:
            last_rowid = 0
            nonlocal remaining
            with get_connection(self.db_path) as con:
                while True:
                    effective_limit = page_size if remaining is None else min(page_size, remaining)
                    if effective_limit <= 0:
                        return
                    sql = f"""
                        SELECT rowid AS _export_rowid, {select_columns}
                        FROM {quoted_table}
                        WHERE rowid > ?
                          AND ({where})
                        ORDER BY rowid ASC
                        LIMIT ?
                    """
                    rows = con.execute(
                        sql,
                        [last_rowid, *date_params, effective_limit],
                    ).fetchall()
                    if not rows:
                        return
                    chunk: list[dict[str, Any]] = []
                    for row in rows:
                        row_dict = dict(row)
                        last_rowid = int(row_dict.pop("_export_rowid"))
                        chunk.append(row_dict)
                    if remaining is not None:
                        remaining -= len(chunk)
                    yield chunk, usable_date_columns

        return _iterator(), usable_date_columns

    def rows_for_date(
        self,
        *,
        table: str,
        target_date: str,
        date_columns: Iterable[str],
        limit: int | None = None,
    ) -> tuple[list[dict[str, Any]], list[str]]:
        """Return rows where any known timestamp/date column falls on target_date."""
        rows: list[dict[str, Any]] = []
        iterator, usable_date_columns = self.iter_rows_for_date(
            table=table,
            target_date=target_date,
            date_columns=date_columns,
            limit=limit,
        )
        for chunk, _date_columns in iterator:
            rows.extend(chunk)
        return rows, usable_date_columns
