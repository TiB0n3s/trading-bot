#!/usr/bin/env python3
"""Compatibility read-model wrapper for trading ledger summaries.

SQL ownership lives in repositories. This module remains as the stable import
surface for status/debug code that expects `data_layer.ledger`.
"""

from __future__ import annotations

from typing import Any

from repositories.ledger_repo import LedgerRepository


def _repository(db_path=None) -> LedgerRepository:
    return LedgerRepository(db_path=db_path) if db_path is not None else LedgerRepository()


def table_exists(table_name: str, db_path=None) -> bool:
    return _repository(db_path).table_exists(table_name)


def table_columns(table_name: str, db_path=None) -> list[str]:
    return _repository(db_path).table_columns(table_name)


def trades_columns(db_path=None) -> list[str]:
    return _repository(db_path).trades_columns()


def count_rows(table_name: str, db_path=None) -> int:
    return _repository(db_path).count_rows(table_name)


def latest_trade_rows(limit: int = 10, db_path=None) -> list[dict[str, Any]]:
    return _repository(db_path).latest_trade_rows(limit)


def ledger_summary(db_path=None) -> dict[str, Any]:
    return _repository(db_path).ledger_summary()
