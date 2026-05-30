"""Small request/response helpers for Flask routes."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any, Callable

from flask import abort, jsonify


@dataclass(frozen=True)
class RequestAuthService:
    validate_secret: Callable[[Any], None]

    def require_valid_secret(self, req: Any) -> None:
        self.validate_secret(req)


@dataclass(frozen=True)
class WebhookPayloadParser:
    approved_symbols: set[str]
    price_ranges: dict[str, tuple[float, float]]
    logger: Any

    def parse(self, req: Any) -> dict:
        if not req.is_json:
            self.logger.warning("Non-JSON payload received")
            abort(400)

        data = req.get_json()
        if data is None:
            self.logger.warning("Empty or unparseable JSON payload")
            abort(400)

        self.logger.info(f"Signal received: {data}")
        action = str(data.get("action", "")).lower()
        symbol = str(data.get("symbol", "")).upper()
        price = data.get("price", 0)

        if not action or not symbol:
            self.logger.warning("Missing action or symbol")
            abort(400)
        if action not in ("buy", "sell"):
            self.logger.warning(f"Unknown action: {action}")
            abort(400)
        if symbol not in self.approved_symbols:
            self.logger.warning(f"Rejected unapproved symbol: {symbol}")
            abort(400)

        try:
            price = float(price)
        except (TypeError, ValueError):
            self.logger.warning(f"Non-numeric price rejected: {price!r}")
            abort(400)

        if price <= 0:
            self.logger.warning(f"Non-positive price rejected for {symbol}: {price}")
            abort(400)

        low, high = self.price_ranges[symbol]
        if not (low * 0.8 <= price <= high * 1.2):
            self.logger.warning(
                f"Price sanity check failed for {symbol}: {price} "
                f"outside [{low * 0.8:.2f}, {high * 1.2:.2f}]"
            )
            abort(400)

        data["action"] = action
        data["symbol"] = symbol
        data["price"] = price
        return data


class ResponseFactory:
    def json(self, payload: dict, status: int = 200):
        return jsonify(payload), status

    def timestamp(self) -> str:
        return datetime.now().isoformat()
