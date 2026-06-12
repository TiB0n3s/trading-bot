import asyncio
import os
import sys
from pathlib import Path
from types import SimpleNamespace

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.fill_stream_service import FillEventHandler


class FakeFillRepository:
    def __init__(self):
        self.events = []
        self.updates = []
        self.synthetic = []

    def init_fill_events_table(self):
        self.initialized = True

    def record_fill_event(self, event, order):
        self.events.append((event, order))

    def update_trade_fill(self, order_id, status, fill_price, filled_qty):
        self.updates.append((order_id, status, fill_price, filled_qty))
        return 1

    def trade_order_exists(self, order_id):
        return False

    def insert_synthetic_fill(self, **kwargs):
        self.synthetic.append(kwargs)
        return True

    def insert_synthetic_exit(self, **kwargs):
        self.synthetic.append(kwargs)
        return True


class FakeFeedbackService:
    def __init__(self):
        self.snapshots = []

    def capture_performance_snapshot(self, *args, **kwargs):
        self.snapshots.append({"args": args, **kwargs})
        return {
            "status": "ok",
            "same_day_closed_trades": 1,
            "same_day_avg_pnl_pct": 0.25,
            "evidence_keys": ["fill"],
        }


def _event(event="fill"):
    return SimpleNamespace(
        event=event,
        order={
            "id": "order-1",
            "symbol": "AAPL",
            "side": "buy",
            "filled_qty": "1",
            "status": "filled",
            "filled_avg_price": "101.25",
        },
    )


def _logger():
    return SimpleNamespace(
        info=lambda *a, **k: None,
        warning=lambda *a, **k: None,
        error=lambda *a, **k: None,
    )


def test_fill_stream_handler_noops_outside_market_hours():
    repo = FakeFillRepository()
    feedback = FakeFeedbackService()
    handler = FillEventHandler(
        repository=repo,
        logger=_logger(),
        feedback_service=feedback,
        market_hours_fn=lambda: False,
    )

    asyncio.run(handler.trade_update_handler(_event()))

    assert repo.events == []
    assert repo.updates == []
    assert repo.synthetic == []
    assert feedback.snapshots == []


def test_fill_stream_handler_records_fill_during_market_hours():
    os.environ["INTRADAY_POST_FILL_LEARNING_ENABLED"] = "true"
    repo = FakeFillRepository()
    feedback = FakeFeedbackService()
    handler = FillEventHandler(
        repository=repo,
        logger=_logger(),
        feedback_service=feedback,
        market_hours_fn=lambda: True,
    )

    asyncio.run(handler.trade_update_handler(_event()))

    assert len(repo.events) == 1
    assert repo.updates == [("order-1", "filled", 101.25, "1")]
    assert len(feedback.snapshots) == 1


if __name__ == "__main__":
    tests = [
        test_fill_stream_handler_noops_outside_market_hours,
        test_fill_stream_handler_records_fill_during_market_hours,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} fill stream service tests passed.")
