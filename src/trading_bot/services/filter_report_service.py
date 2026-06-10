"""Filter effectiveness report data service."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any

from repositories.filter_report_repo import FilterReportRepository, TradeFilter


@dataclass(frozen=True)
class FilterReportPayload:
    rows: list[dict[str, Any]]
    total_signals: int
    approved_signals: int
    rejected_signals: int
    symbol: str | None = None


class FilterReportService:
    def __init__(self, *, repository: FilterReportRepository):
        self.repository = repository

    def build_filter(
        self,
        *,
        target_date: str | None = None,
        week: bool = False,
        all_history: bool = False,
        symbol: str | None = None,
    ) -> TradeFilter:
        if all_history:
            return TradeFilter(symbol=symbol.upper() if symbol else None)

        if week:
            today = date.today()
            monday = today - timedelta(days=today.weekday())
            saturday = monday + timedelta(days=5)
            return TradeFilter(
                start_date=monday.isoformat(),
                end_date=saturday.isoformat(),
                symbol=symbol.upper() if symbol else None,
            )

        target = target_date or date.today().isoformat()
        return TradeFilter(
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
    ) -> FilterReportPayload:
        if not self.repository.db_exists():
            raise FileNotFoundError(self.repository.db_path)

        trade_filter = self.build_filter(
            target_date=target_date,
            week=week,
            all_history=all_history,
            symbol=symbol,
        )
        rows = self.repository.rejected_rows(trade_filter)
        return FilterReportPayload(
            rows=rows,
            total_signals=self.repository.total_signals(trade_filter),
            approved_signals=self.repository.approved_signals(trade_filter),
            rejected_signals=len(rows),
            symbol=symbol.upper() if symbol else None,
        )


def build_default_filter_report_service(db_path=None) -> FilterReportService:
    repository = (
        FilterReportRepository(db_path=db_path) if db_path is not None else FilterReportRepository()
    )
    return FilterReportService(repository=repository)
