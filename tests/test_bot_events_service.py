import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.bot_events_service import BotEventsService


class FakeRepository:
    def __init__(self, raises=False, rows=None):
        self.raises = raises
        self.rows = rows or []
        self.init_calls = 0
        self.inserted = []
        self.fetch_kwargs = None

    def init_table(self):
        self.init_calls += 1
        if self.raises:
            raise RuntimeError("db unavailable")

    def insert_event(self, event):
        if self.raises:
            raise RuntimeError("db unavailable")
        self.inserted.append(dict(event))

    def fetch_events(self, **kwargs):
        self.fetch_kwargs = kwargs
        return self.rows


def test_log_event_serializes_payload_and_delegates_insert():
    repo = FakeRepository()
    service = BotEventsService(repo)

    ok = service.log_event(
        event_type="DECISION_POLICY_SIZE_DOWN",
        symbol="AAPL",
        action="buy",
        decision="size_down",
        severity="medium",
        reason="test",
        source="unit",
        payload={"b": 2, "a": 1},
    )

    assert ok is True
    assert repo.init_calls == 1
    assert len(repo.inserted) == 1
    event = repo.inserted[0]
    assert event["event_type"] == "DECISION_POLICY_SIZE_DOWN"
    assert event["symbol"] == "AAPL"
    assert event["payload_json"] == '{"a": 1, "b": 2}'
    assert event["timestamp"]


def test_log_event_is_fail_open():
    service = BotEventsService(FakeRepository(raises=True))

    assert service.log_event(event_type="TEST") is False


def test_fetch_events_initializes_and_delegates_filters():
    rows = [{"id": 1}]
    repo = FakeRepository(rows=rows)
    service = BotEventsService(repo)

    result = service.fetch_events(limit=5, event_type="TEST", symbol="aapl", since="2026-05-30")

    assert result == rows
    assert repo.init_calls == 1
    assert repo.fetch_kwargs == {
        "limit": 5,
        "event_type": "TEST",
        "symbol": "aapl",
        "since": "2026-05-30",
    }


if __name__ == "__main__":
    tests = [
        test_log_event_serializes_payload_and_delegates_insert,
        test_log_event_is_fail_open,
        test_fetch_events_initializes_and_delegates_filters,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} bot events service tests passed.")
