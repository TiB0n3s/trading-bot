"""Prior-session context formatting for entry intelligence."""

from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import Any, Callable

from market_time import is_trading_day, now_et
from repositories.prior_session_context_repo import PriorSessionContextRepository


def parse_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return datetime.strptime(str(value)[:10], "%Y-%m-%d").date()
    except Exception:
        return None


def trading_days_between(
    start: date,
    end: date,
    *,
    is_trading_day_fn: Callable[[date], bool] = is_trading_day,
) -> int | None:
    if start > end:
        return None
    days = 0
    current = start + timedelta(days=1)
    while current <= end:
        if is_trading_day_fn(current):
            days += 1
        current += timedelta(days=1)
    return days


class PriorSessionContextService:
    def __init__(
        self,
        *,
        repository: PriorSessionContextRepository,
        now_et_fn=now_et,
        is_trading_day_fn=is_trading_day,
    ):
        self.repository = repository
        self.now_et = now_et_fn
        self.is_trading_day = is_trading_day_fn

    def prior_session_context(self, symbol: str) -> dict[str, Any] | None:
        symbol = (symbol or "").upper().strip()
        if not symbol:
            return None

        try:
            row = self.repository.latest_strong_day_participation(symbol)
        except Exception:
            return None

        if not row:
            return None

        market_date = parse_date(row.get("market_date"))
        today = self.now_et().date()
        age_days = (
            trading_days_between(
                market_date,
                today,
                is_trading_day_fn=self.is_trading_day,
            )
            if market_date
            else None
        )
        signal_count = int(
            (row.get("buy_signal_count") or 0)
            + (row.get("sell_signal_count") or 0)
            + (row.get("auto_buy_candidate_count") or 0)
        )
        participated = bool(
            (row.get("approved_buy_count") or 0)
            or (row.get("rejected_buy_count") or 0)
            or (row.get("auto_buy_candidate_count") or 0)
        )

        return {
            "market_date": row.get("market_date"),
            "session_return_pct": row.get("session_return_pct"),
            "participated": participated,
            "signal_count": signal_count,
            "participation_quality": row.get("primary_status"),
            "session_age_days": age_days,
        }


def build_default_prior_session_context_service(db_path=None) -> PriorSessionContextService:
    repository = (
        PriorSessionContextRepository(db_path=db_path)
        if db_path is not None
        else PriorSessionContextRepository()
    )
    return PriorSessionContextService(repository=repository)
