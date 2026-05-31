"""Analysis service for canonical entry/exit lifecycle rows."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from repositories.lifecycle_analysis_repo import LifecycleAnalysisRepository


@dataclass(frozen=True)
class LifecycleAnalysisPayload:
    rows: list[dict[str, Any]]
    start_date: str
    end_date: str
    symbol: str | None
    summary: dict[str, int]


class LifecycleAnalysisService:
    def __init__(self, repository: LifecycleAnalysisRepository):
        self.repository = repository

    @staticmethod
    def _classify(row: dict[str, Any]) -> str:
        if row.get("approved") and row.get("exit_snapshot_id"):
            return "approved_with_exit"
        if row.get("approved"):
            return "approved_open_or_unlinked_exit"
        if row.get("rejected_outcome_id"):
            return "rejected_with_counterfactual"
        if row.get("trade_id") is None:
            return "rejected_snapshot_only_no_trade"
        return "rejected_without_counterfactual"

    def payload(
        self,
        *,
        start_date: str,
        end_date: str | None = None,
        symbol: str | None = None,
        limit: int | None = None,
    ) -> LifecycleAnalysisPayload:
        end = end_date or start_date
        raw_rows = self.repository.lifecycle_rows(
            start_date=start_date,
            end_date=end,
            symbol=symbol,
            limit=limit,
        )
        rows = []
        summary = {
            "rows": 0,
            "approved_with_exit": 0,
            "approved_open_or_unlinked_exit": 0,
            "rejected_with_counterfactual": 0,
            "rejected_snapshot_only_no_trade": 0,
            "rejected_without_counterfactual": 0,
        }
        for raw in raw_rows:
            row = dict(raw)
            lifecycle_status = self._classify(row)
            row["lifecycle_status"] = lifecycle_status
            rows.append(row)
            summary["rows"] += 1
            summary[lifecycle_status] += 1

        return LifecycleAnalysisPayload(
            rows=rows,
            start_date=start_date,
            end_date=end,
            symbol=symbol.upper() if symbol else None,
            summary=summary,
        )


def build_default_lifecycle_analysis_service(db_path=None) -> LifecycleAnalysisService:
    repository = (
        LifecycleAnalysisRepository(db_path=db_path)
        if db_path is not None
        else LifecycleAnalysisRepository()
    )
    return LifecycleAnalysisService(repository)
