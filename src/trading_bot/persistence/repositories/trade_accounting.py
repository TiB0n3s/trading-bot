"""Shared SQL predicates for trade execution accounting."""

from __future__ import annotations


def fill_bearing_order_condition(alias: str | None = None) -> str:
    """Return SQL that treats partial-fill-then-cancel rows as executions.

    Alpaca can leave an order in ``canceled`` status after a partial fill while
    still reporting filled quantity and average fill price. For position/P&L
    accounting those rows must count as fill-bearing; empty canceled orders must
    not.
    """

    prefix = f"{alias}." if alias else ""
    return (
        f"(LOWER(COALESCE({prefix}order_status, '')) IN ('filled', 'partially_filled') "
        f"OR (LOWER(COALESCE({prefix}order_status, '')) = 'canceled' "
        f"AND {prefix}fill_price IS NOT NULL "
        f"AND COALESCE({prefix}qty, 0) > 0))"
    )
