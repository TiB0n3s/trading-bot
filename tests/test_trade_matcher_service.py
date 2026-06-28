import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.trade_matcher_service import TradeMatcherService


class FakeRepository:
    def __init__(self, rows=None):
        self.rows = rows or []
        self.replaced = None
        self.initialized = False

    def load_filled_trades(self):
        return list(self.rows)

    def load_position_manager_sells(self):
        return []

    def existing_synthetic_order_ids(self):
        return set()

    def event_payload_for_order(self, order_id):
        return None

    def init_matched_trades_table(self):
        self.initialized = True

    def replace_matched_trades(self, matched, columns):
        self.replaced = (list(matched), list(columns))


def test_match_trades_uses_fifo_and_preserves_open_lots():
    repo = FakeRepository(
        [
            {
                "timestamp": "2026-05-30T10:00:00",
                "symbol": "QQQ",
                "action": "buy",
                "qty": 2,
                "fill_price": 100,
                "order_id": "buy-1",
                "setup_label": "test_setup",
            },
            {
                "timestamp": "2026-05-30T10:05:00",
                "symbol": "QQQ",
                "action": "sell",
                "qty": 1,
                "fill_price": 105,
                "order_id": "sell-1",
                "rejection_reason": "position_manager_partial_exit",
            },
        ]
    )
    service = TradeMatcherService(
        repository=repo,
        symbol_signal_source={"QQQ": "tradingview"},
    )

    matched, open_lots = service.match_trades()

    assert len(matched) == 1
    assert matched[0]["symbol"] == "QQQ"
    assert matched[0]["qty"] == 1.0
    assert matched[0]["realized_pnl"] == 5.0
    assert matched[0]["setup_label"] == "test_setup"
    assert matched[0]["entry_order_id"] == "buy-1"
    assert matched[0]["entry_source"] == "webhook_buy"
    assert matched[0]["exit_order_id"] == "sell-1"
    assert matched[0]["signal_source"] == "tradingview"
    assert open_lots["QQQ"][0]["qty"] == 1.0


def test_rebuild_initializes_and_replaces_rows():
    repo = FakeRepository(
        [
            {
                "timestamp": "2026-05-30T10:00:00",
                "symbol": "AAPL",
                "action": "buy",
                "qty": 1,
                "fill_price": 10,
            },
            {
                "timestamp": "2026-05-30T10:01:00",
                "symbol": "AAPL",
                "action": "sell",
                "qty": 1,
                "fill_price": 11,
            },
        ]
    )
    service = TradeMatcherService(repository=repo)

    matched, _ = service.rebuild_matched_trades()

    assert repo.initialized is True
    assert repo.replaced[0] == matched
    assert "symbol" in repo.replaced[1]
    assert "match_source" in repo.replaced[1]
    assert "entry_order_id" in repo.replaced[1]


def test_auto_buy_entries_are_labeled_in_lifecycle_matches():
    repo = FakeRepository(
        [
            {
                "timestamp": "2026-05-30T10:00:00",
                "symbol": "SOFI",
                "action": "buy",
                "qty": 1,
                "fill_price": 10,
                "order_id": "auto-buy-1",
                "confidence": "auto_buy_manager",
                "rejection_reason": "auto_buy_manager: internal bar-derived buy submitted",
            },
            {
                "timestamp": "2026-05-30T10:20:00",
                "symbol": "SOFI",
                "action": "sell",
                "qty": 1,
                "fill_price": 10.5,
                "order_id": "sell-1",
            },
        ]
    )
    service = TradeMatcherService(repository=repo)

    matched, _ = service.match_trades()

    assert len(matched) == 1
    assert matched[0]["entry_source"] == "auto_buy_manager"
    assert matched[0]["entry_order_id"] == "auto-buy-1"


def test_unmatched_prior_sell_prevents_false_open_lot_when_net_flat():
    repo = FakeRepository(
        [
            {
                "timestamp": "2026-05-30T09:30:00",
                "symbol": "DKS",
                "action": "sell",
                "qty": 2,
                "fill_price": 229,
                "order_id": "unmatched-exit",
            },
            {
                "timestamp": "2026-05-30T10:00:00",
                "symbol": "DKS",
                "action": "buy",
                "qty": 2,
                "fill_price": 231,
                "order_id": "later-buy",
            },
        ]
    )
    service = TradeMatcherService(repository=repo)

    matched, open_lots = service.match_trades()

    assert matched == []
    assert "DKS" not in open_lots


def test_unmatched_sell_is_surfaced_not_silently_dropped():
    """An exit with no open entry lot must be tracked, not silently discarded."""
    repo = FakeRepository(
        [
            {
                "timestamp": "2026-05-30T09:30:00",
                "symbol": "DKS",
                "action": "sell",
                "qty": 3,
                "fill_price": 229,
                "order_id": "orphan-exit",
            },
        ]
    )
    service = TradeMatcherService(repository=repo)

    matched, open_lots = service.match_trades()

    assert matched == []
    assert service.last_unmatched_sells == {"DKS": 3.0}


if __name__ == "__main__":
    tests = [
        test_match_trades_uses_fifo_and_preserves_open_lots,
        test_rebuild_initializes_and_replaces_rows,
        test_auto_buy_entries_are_labeled_in_lifecycle_matches,
        test_unmatched_prior_sell_prevents_false_open_lot_when_net_flat,
        test_unmatched_sell_is_surfaced_not_silently_dropped,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} trade matcher service tests passed.")
