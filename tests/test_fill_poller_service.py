import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.fill_poller_service import FillPollerService


class FakeRepository:
    def __init__(self):
        self.rows = [
            {"id": 1, "order_id": "order-1", "symbol": "AAPL"},
            {"id": 2, "order_id": "order-2", "symbol": "MSFT"},
            {"id": 3, "order_id": "order-3", "symbol": "TSLA"},
        ]
        self.current = {
            1: {"order_status": "new", "fill_price": None},
            2: {"order_status": "filled", "fill_price": 100.0},
            3: {"order_status": "new", "fill_price": None},
        }
        self.updates = []

    def pending_trade_orders(self, statuses):
        self.statuses = statuses
        return self.rows

    def trade_status_by_id(self, trade_id):
        return self.current[trade_id]

    def update_trade_status_by_id(self, *, trade_id, status, fill_price):
        self.updates.append({"trade_id": trade_id, "status": status, "fill_price": fill_price})
        return 1


class FakeBroker:
    def get_order(self, order_id):
        if order_id == "order-1":
            return SimpleNamespace(status="filled", filled_avg_price="101.25")
        if order_id == "order-2":
            return SimpleNamespace(status="filled", filled_avg_price="100.0")
        raise RuntimeError("broker unavailable")


def test_fill_poller_updates_skips_and_counts_errors():
    repo = FakeRepository()
    service = FillPollerService(
        broker_service=FakeBroker(),
        repository=repo,
        logger=SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None),
        market_hours_fn=lambda: True,
    )

    result = service.poll_fills()

    assert result.checked == 3
    assert result.updated == 1
    assert result.skipped == 2
    assert repo.updates == [{"trade_id": 1, "status": "filled", "fill_price": 101.25}]


def test_fill_poller_noops_outside_market_hours():
    repo = FakeRepository()
    service = FillPollerService(
        broker_service=FakeBroker(),
        repository=repo,
        logger=SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None),
        market_hours_fn=lambda: False,
    )

    result = service.poll_fills()

    assert result.checked == 0
    assert result.updated == 0
    assert result.skipped == 0
    assert repo.updates == []
    assert not hasattr(repo, "statuses")


if __name__ == "__main__":
    tests = [
        test_fill_poller_updates_skips_and_counts_errors,
        test_fill_poller_noops_outside_market_hours,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} fill poller service tests passed.")
