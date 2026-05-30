"""Centralized broker account, position, and order access."""

from __future__ import annotations

from typing import Any

import broker


class BrokerService:
    def __init__(self, broker_module=broker):
        self.broker = broker_module

    def get_account(self) -> dict[str, Any] | None:
        return self.broker.get_account()

    def get_position(self, symbol: str) -> dict[str, Any] | None:
        return self.broker.get_position(symbol)

    def place_order(
        self,
        symbol: str,
        action: str,
        position_size_pct: float,
        stop_loss_pct: float,
        take_profit_pct: float,
        risk_level: str | None = None,
        client_order_id: str | None = None,
        qty_override: int | None = None,
    ) -> dict[str, Any] | None:
        return self.broker.place_order(
            symbol=symbol,
            action=action,
            position_size_pct=position_size_pct,
            stop_loss_pct=stop_loss_pct,
            take_profit_pct=take_profit_pct,
            risk_level=risk_level,
            client_order_id=client_order_id,
            qty_override=qty_override,
        )

    def list_positions(self) -> list[Any]:
        return list(self.broker.api.list_positions() or [])

    def assert_position_exists(self, symbol: str) -> None:
        self.broker.api.get_position(str(symbol or "").strip().upper())

    def list_open_orders(self, symbol: str | None = None) -> list[Any]:
        kwargs: dict[str, Any] = {"status": "open"}
        if symbol:
            kwargs["symbols"] = [str(symbol).strip().upper()]
        return list(self.broker.api.list_orders(**kwargs) or [])

    def cancel_order(self, order_id: str) -> None:
        self.broker.api.cancel_order(order_id)

    def submit_market_sell(self, symbol: str, qty: float | int) -> Any:
        return self.broker.api.submit_order(
            symbol=str(symbol or "").strip().upper(),
            qty=qty,
            side="sell",
            type="market",
            time_in_force="day",
        )

    def get_order(self, order_id: str) -> Any:
        return self.broker.api.get_order(order_id)


_default_broker_service: BrokerService | None = None


def get_default_broker_service() -> BrokerService:
    global _default_broker_service
    if _default_broker_service is None:
        _default_broker_service = BrokerService()
    return _default_broker_service


class _BrokerServiceProxy:
    """Backward-compatible lazy proxy for scripts not yet using the container."""

    def __getattr__(self, name: str) -> Any:
        return getattr(get_default_broker_service(), name)


broker_service = _BrokerServiceProxy()
