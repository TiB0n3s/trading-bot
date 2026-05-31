"""Blocked signal outcome report data service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from repositories.blocked_signal_outcome_repo import (
    BlockedSignalFilter,
    BlockedSignalOutcomeRepository,
)


@dataclass(frozen=True)
class BlockedSignalOutcomePayload:
    rows: list[dict[str, Any]]
    symbol: str | None = None
    category: str | None = None


class BlockedSignalOutcomeService:
    def __init__(self, *, repository: BlockedSignalOutcomeRepository):
        self.repository = repository

    def build_filter(
        self,
        *,
        target_date: str | None = None,
        week: bool = False,
        all_history: bool = False,
        symbol: str | None = None,
    ) -> BlockedSignalFilter:
        if all_history:
            return BlockedSignalFilter(symbol=symbol.upper() if symbol else None)

        if week:
            today = date.today()
            monday = today - timedelta(days=today.weekday())
            saturday = monday + timedelta(days=5)
            return BlockedSignalFilter(
                start_date=monday.isoformat(),
                end_date=saturday.isoformat(),
                symbol=symbol.upper() if symbol else None,
            )

        target = target_date or date.today().isoformat()
        return BlockedSignalFilter(
            target_like=f"{target}%",
            symbol=symbol.upper() if symbol else None,
        )

    def payload(
        self,
        *,
        target_date: str | None = None,
        week: bool = False,
        all_history: bool = False,
        symbol: str | None = None,
        category: str | None = None,
        category_fn=None,
    ) -> BlockedSignalOutcomePayload:
        if not self.repository.db_exists():
            raise FileNotFoundError(self.repository.db_path)

        signal_filter = self.build_filter(
            target_date=target_date,
            week=week,
            all_history=all_history,
            symbol=symbol,
        )
        rows = self.repository.blocked_buy_rows(signal_filter)
        if category and category_fn:
            rows = [row for row in rows if category_fn(row["rejection_reason"]) == category]

        return BlockedSignalOutcomePayload(
            rows=rows,
            symbol=symbol.upper() if symbol else None,
            category=category,
        )


def build_default_blocked_signal_outcome_service(db_path=None) -> BlockedSignalOutcomeService:
    repository = (
        BlockedSignalOutcomeRepository(db_path=db_path)
        if db_path is not None
        else BlockedSignalOutcomeRepository()
    )
    return BlockedSignalOutcomeService(repository=repository)
