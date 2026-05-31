import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from repositories.blocked_signal_outcome_repo import BlockedSignalFilter
from services.blocked_signal_outcome_service import BlockedSignalOutcomeService


class FakeRepository:
    def __init__(self, exists=True):
        self.db_path = Path("fake.db")
        self.exists = exists
        self.filters = []

    def db_exists(self):
        return self.exists

    def blocked_buy_rows(self, signal_filter):
        self.filters.append(signal_filter)
        return [
            {"symbol": "AAPL", "rejection_reason": "prediction_gate: weak"},
            {"symbol": "QQQ", "rejection_reason": "confidence_gate: low"},
        ]


def test_payload_builds_filter_and_applies_category():
    repo = FakeRepository()
    service = BlockedSignalOutcomeService(repository=repo)

    payload = service.payload(
        target_date="2026-05-30",
        symbol="aapl",
        category="prediction_gate",
        category_fn=lambda reason: reason.split(":", 1)[0],
    )

    assert repo.filters == [
        BlockedSignalFilter(target_like="2026-05-30%", symbol="AAPL")
    ]
    assert payload.symbol == "AAPL"
    assert payload.category == "prediction_gate"
    assert payload.rows == [{"symbol": "AAPL", "rejection_reason": "prediction_gate: weak"}]


def test_missing_db_raises_file_not_found():
    service = BlockedSignalOutcomeService(repository=FakeRepository(exists=False))

    try:
        service.payload(target_date="2026-05-30")
    except FileNotFoundError:
        return

    raise AssertionError("expected FileNotFoundError")


if __name__ == "__main__":
    tests = [
        test_payload_builds_filter_and_applies_category,
        test_missing_db_raises_file_not_found,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} blocked signal outcome service tests passed.")
