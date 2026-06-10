"""Entry-quality report data service."""

from __future__ import annotations

from typing import Any

from repositories.entry_quality_repo import EntryQualityRepository


class EntryQualityService:
    def __init__(self, *, repository: EntryQualityRepository):
        self.repository = repository

    def rows(self, target_date: str | None, all_history: bool = False) -> list[dict[str, Any]]:
        if all_history:
            return self.repository.rows_all()
        return self.repository.rows_for_date(target_date or "")


def build_default_entry_quality_service(db_path=None) -> EntryQualityService:
    repository = (
        EntryQualityRepository(db_path=db_path) if db_path is not None else EntryQualityRepository()
    )
    return EntryQualityService(repository=repository)
