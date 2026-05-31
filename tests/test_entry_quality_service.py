import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.entry_quality_service import EntryQualityService


class FakeRepository:
    def __init__(self):
        self.calls = []

    def rows_for_date(self, target_date):
        self.calls.append(("date", target_date))
        return [{"symbol": "AAPL"}]

    def rows_all(self):
        self.calls.append(("all",))
        return [{"symbol": "QQQ"}]


def test_entry_quality_service_selects_date_rows():
    repo = FakeRepository()
    service = EntryQualityService(repository=repo)

    assert service.rows("2026-05-30") == [{"symbol": "AAPL"}]
    assert repo.calls == [("date", "2026-05-30")]


def test_entry_quality_service_selects_all_history_rows():
    repo = FakeRepository()
    service = EntryQualityService(repository=repo)

    assert service.rows(None, all_history=True) == [{"symbol": "QQQ"}]
    assert repo.calls == [("all",)]


if __name__ == "__main__":
    tests = [
        test_entry_quality_service_selects_date_rows,
        test_entry_quality_service_selects_all_history_rows,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} entry quality service tests passed.")
