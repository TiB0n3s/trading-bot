"""Orchestration for daily and weekly summary report data."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Any, Callable

from repositories.summary_repo import SummaryRepository
from trade_matcher import rebuild_matched_trades


@dataclass(frozen=True)
class SummaryPayload:
    rows: list[dict[str, Any]]
    matched: list[dict[str, Any]]
    trade_rows: list[dict[str, Any]]
    header: str


class DailySummaryService:
    def __init__(
        self,
        *,
        repository: SummaryRepository,
        refresh_matched: Callable[[], None] = rebuild_matched_trades,
        warning_sink: Callable[[str], None] | None = None,
    ):
        self.repository = repository
        self.refresh_matched = refresh_matched
        self.warning_sink = warning_sink

    def _refresh_matched(self) -> None:
        try:
            self.refresh_matched()
        except Exception as e:
            if self.warning_sink:
                self.warning_sink(f"WARNING: matched_trades rebuild failed: {e}")

    def daily_payload(self, target_date: str | None = None) -> SummaryPayload:
        target_date = target_date or str(date.today())
        self._refresh_matched()
        return SummaryPayload(
            rows=self.repository.trades_for_day(target_date),
            matched=self.repository.matched_trades_for_day(target_date),
            trade_rows=self.repository.trade_context_rows_for_day(target_date),
            header=f"DAILY SUMMARY — {target_date}",
        )

    def weekly_payload(self, target_date: str | None = None) -> SummaryPayload:
        if target_date:
            ref = date.fromisoformat(target_date)
        else:
            today = date.today()
            if today.weekday() >= 5:
                ref = today - timedelta(days=today.weekday() - 4)
            else:
                ref = today

        monday = ref - timedelta(days=ref.weekday())
        friday = monday + timedelta(days=4)
        end_excl = (friday + timedelta(days=1)).isoformat()

        self._refresh_matched()
        return SummaryPayload(
            rows=self.repository.trades_for_range(monday.isoformat(), end_excl),
            matched=self.repository.matched_trades_for_range(
                monday.isoformat(),
                end_excl,
            ),
            trade_rows=self.repository.trade_context_rows_for_range(
                monday.isoformat(),
                end_excl,
            ),
            header=f"WEEKLY SUMMARY — {monday} to {friday}",
        )


def build_default_daily_summary_service(warning_sink=None, db_path=None) -> DailySummaryService:
    repository = SummaryRepository(db_path=db_path) if db_path is not None else SummaryRepository()
    return DailySummaryService(repository=repository, warning_sink=warning_sink)
