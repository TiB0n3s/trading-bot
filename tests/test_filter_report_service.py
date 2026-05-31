import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories.filter_report_repo import TradeFilter
from services.filter_report_service import FilterReportService


class FakeRepository:
    def __init__(self, exists=True):
        self.db_path = Path("fake.db")
        self.exists = exists
        self.filters = []

    def db_exists(self):
        return self.exists

    def rejected_rows(self, trade_filter):
        self.filters.append(("rows", trade_filter))
        return [{"symbol": "AAPL", "rejection_reason": "confidence_gate: low"}]

    def total_signals(self, trade_filter):
        self.filters.append(("total", trade_filter))
        return 10

    def approved_signals(self, trade_filter):
        self.filters.append(("approved", trade_filter))
        return 7


def test_payload_builds_date_and_symbol_filter():
    repo = FakeRepository()
    service = FilterReportService(repository=repo)

    payload = service.payload(target_date="2026-05-30", symbol="aapl")

    assert payload.total_signals == 10
    assert payload.approved_signals == 7
    assert payload.rejected_signals == 1
    assert payload.symbol == "AAPL"
    assert repo.filters[0] == (
        "rows",
        TradeFilter(target_like="2026-05-30%", symbol="AAPL"),
    )


def test_missing_db_raises_file_not_found():
    service = FilterReportService(repository=FakeRepository(exists=False))

    try:
        service.payload(target_date="2026-05-30")
    except FileNotFoundError:
        return

    raise AssertionError("expected FileNotFoundError")


if __name__ == "__main__":
    tests = [
        test_payload_builds_date_and_symbol_filter,
        test_missing_db_raises_file_not_found,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} filter report service tests passed.")
