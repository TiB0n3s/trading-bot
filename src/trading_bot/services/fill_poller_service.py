"""Broker fill polling orchestration."""

from __future__ import annotations

import logging
from dataclasses import dataclass

from market_time import is_market_hours

from repositories import fill_repo

PENDING_STATUSES = ("pending_new", "new", "partially_filled")


@dataclass(frozen=True)
class FillPollerResult:
    checked: int
    updated: int
    skipped: int


class FillPollerService:
    def __init__(
        self,
        *,
        broker_service,
        repository=fill_repo,
        logger: logging.Logger | None = None,
        pending_statuses: tuple[str, ...] = PENDING_STATUSES,
        market_hours_fn=is_market_hours,
    ):
        self.broker_service = broker_service
        self.repository = repository
        self.logger = logger or logging.getLogger(__name__)
        self.pending_statuses = pending_statuses
        self.market_hours_fn = market_hours_fn

    @classmethod
    def from_container(cls, container) -> "FillPollerService":
        return cls(
            broker_service=container.broker_service,
            logger=getattr(container, "logger", None),
        )

    def poll_fills(self) -> FillPollerResult:
        checked = updated = skipped = 0

        if not self.market_hours_fn():
            return FillPollerResult(checked=checked, updated=updated, skipped=skipped)

        rows = self.repository.pending_trade_orders(self.pending_statuses)

        for row in rows:
            checked += 1
            try:
                order = self.broker_service.get_order(row["order_id"])
                new_status = order.status
                fill_price = float(order.filled_avg_price) if order.filled_avg_price else None

                cur = self.repository.trade_status_by_id(row["id"])

                if cur["order_status"] == new_status and cur["fill_price"] == fill_price:
                    skipped += 1
                    continue

                self.repository.update_trade_status_by_id(
                    trade_id=row["id"],
                    status=new_status,
                    fill_price=fill_price,
                )
                updated += 1
                self.logger.info(
                    f"Updated {row['symbol']} order {row['order_id']}: "
                    f"status={new_status} fill_price={fill_price}"
                )
            except Exception as e:
                self.logger.error(f"Failed to poll order {row['order_id']} ({row['symbol']}): {e}")
                skipped += 1

        self.logger.info(
            f"Poll complete - checked: {checked}, updated: {updated}, skipped: {skipped}"
        )
        return FillPollerResult(checked=checked, updated=updated, skipped=skipped)
