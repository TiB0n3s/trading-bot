import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.daily_summary_service import DailySummaryService


class FakeRepository:
    def __init__(self):
        self.calls = []

    def trades_for_day(self, target_date):
        self.calls.append(("trades_for_day", target_date))
        return [{"id": 1}]

    def matched_trades_for_day(self, target_date):
        self.calls.append(("matched_for_day", target_date))
        return [{"symbol": "AAPL"}]

    def trade_context_rows_for_day(self, target_date):
        self.calls.append(("context_for_day", target_date))
        return [{"setup_label": "x"}]

    def auto_buy_hard_block_audit_for_day(self, target_date):
        self.calls.append(("hard_block_audit_for_day", target_date))
        return {"rows_seen": 1, "counterfactual_strong_rows": 0}

    def trades_for_range(self, start_date, end_date):
        self.calls.append(("trades_for_range", start_date, end_date))
        return [{"id": 2}]

    def matched_trades_for_range(self, start_date, end_date):
        self.calls.append(("matched_for_range", start_date, end_date))
        return [{"symbol": "QQQ"}]

    def trade_context_rows_for_range(self, start_date, end_date):
        self.calls.append(("context_for_range", start_date, end_date))
        return [{"setup_label": "y"}]

    def auto_buy_hard_block_audit_for_range(self, start_date, end_date):
        self.calls.append(("hard_block_audit_for_range", start_date, end_date))
        return {"rows_seen": 2, "counterfactual_strong_rows": 1}


def test_daily_payload_refreshes_and_loads_day_rows():
    refreshed = []
    repo = FakeRepository()
    service = DailySummaryService(
        repository=repo,
        refresh_matched=lambda: refreshed.append(True),
    )

    payload = service.daily_payload("2026-05-30")

    assert refreshed == [True]
    assert payload.rows == [{"id": 1}]
    assert payload.matched == [{"symbol": "AAPL"}]
    assert payload.trade_rows == [{"setup_label": "x"}]
    assert payload.auto_buy_hard_block_audit == {
        "rows_seen": 1,
        "counterfactual_strong_rows": 0,
    }
    assert payload.header == "DAILY SUMMARY — 2026-05-30"
    assert repo.calls == [
        ("trades_for_day", "2026-05-30"),
        ("matched_for_day", "2026-05-30"),
        ("context_for_day", "2026-05-30"),
        ("hard_block_audit_for_day", "2026-05-30"),
    ]


def test_weekly_payload_uses_market_week_range():
    repo = FakeRepository()
    service = DailySummaryService(repository=repo, refresh_matched=lambda: None)

    payload = service.weekly_payload("2026-05-30")

    assert payload.header == "WEEKLY SUMMARY — 2026-05-25 to 2026-05-29"
    assert payload.auto_buy_hard_block_audit == {
        "rows_seen": 2,
        "counterfactual_strong_rows": 1,
    }
    assert repo.calls == [
        ("trades_for_range", "2026-05-25", "2026-05-30"),
        ("matched_for_range", "2026-05-25", "2026-05-30"),
        ("context_for_range", "2026-05-25", "2026-05-30"),
        ("hard_block_audit_for_range", "2026-05-25", "2026-05-30"),
    ]


def test_refresh_failure_is_reported_but_payload_still_loads():
    warnings = []
    repo = FakeRepository()
    service = DailySummaryService(
        repository=repo,
        refresh_matched=lambda: (_ for _ in ()).throw(RuntimeError("boom")),
        warning_sink=warnings.append,
    )

    payload = service.daily_payload("2026-05-30")

    assert payload.rows == [{"id": 1}]
    assert warnings == ["WARNING: matched_trades rebuild failed: boom"]


if __name__ == "__main__":
    tests = [
        test_daily_payload_refreshes_and_loads_day_rows,
        test_weekly_payload_uses_market_week_range,
        test_refresh_failure_is_reported_but_payload_still_loads,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} daily summary service tests passed.")
