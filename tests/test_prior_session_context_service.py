import sys
from datetime import date, datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.prior_session_context_service import (
    PriorSessionContextService,
    parse_date,
    trading_days_between,
)


class FakeRepository:
    def __init__(self, row=None, raises=False):
        self.row = row
        self.raises = raises
        self.symbols = []

    def latest_strong_day_participation(self, symbol):
        self.symbols.append(symbol)
        if self.raises:
            raise RuntimeError("db unavailable")
        return self.row


def _service(row=None, raises=False):
    return PriorSessionContextService(
        repository=FakeRepository(row=row, raises=raises),
        now_et_fn=lambda: datetime(2026, 5, 30),
        is_trading_day_fn=lambda day: day.weekday() < 5,
    )


def test_parse_date_accepts_iso_datetime_prefix():
    assert parse_date("2026-05-29T15:59:00") == date(2026, 5, 29)
    assert parse_date(None) is None
    assert parse_date("not-a-date") is None


def test_trading_days_between_counts_weekdays_after_start():
    assert trading_days_between(
        date(2026, 5, 28),
        date(2026, 6, 1),
        is_trading_day_fn=lambda day: day.weekday() < 5,
    ) == 2
    assert trading_days_between(date(2026, 6, 1), date(2026, 5, 28)) is None


def test_prior_session_context_formats_latest_row():
    row = {
        "market_date": "2026-05-28",
        "session_return_pct": 3.4,
        "primary_status": "strong_participation",
        "buy_signal_count": 2,
        "approved_buy_count": 1,
        "rejected_buy_count": 0,
        "sell_signal_count": 1,
        "auto_buy_candidate_count": 2,
        "auto_buy_strong_count": 1,
    }
    service = _service(row=row)

    result = service.prior_session_context(" aapl ")

    assert result == {
        "market_date": "2026-05-28",
        "session_return_pct": 3.4,
        "participated": True,
        "signal_count": 5,
        "participation_quality": "strong_participation",
        "session_age_days": 1,
    }
    assert service.repository.symbols == ["AAPL"]


def test_prior_session_context_returns_none_for_missing_or_failed_reads():
    assert _service(row=None).prior_session_context("AAPL") is None
    assert _service(row={}, raises=True).prior_session_context("AAPL") is None
    assert _service(row={}).prior_session_context("") is None


if __name__ == "__main__":
    tests = [
        test_parse_date_accepts_iso_datetime_prefix,
        test_trading_days_between_counts_weekdays_after_start,
        test_prior_session_context_formats_latest_row,
        test_prior_session_context_returns_none_for_missing_or_failed_reads,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    print(f"\nAll {len(tests)} prior session context service tests passed.")
