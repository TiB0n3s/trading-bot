"""Repository helpers for rejection persistence."""

from __future__ import annotations

from typing import Any

from repositories.trades_repo import insert_trade_row


def insert_rejection_row(columns: list[str], values: list[Any]) -> int:
    return insert_trade_row(columns, values)

