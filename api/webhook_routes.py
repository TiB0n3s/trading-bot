"""Webhook HTTP route."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from flask import Blueprint, request

from api.request_services import RequestAuthService, ResponseFactory, WebhookPayloadParser


@dataclass(frozen=True)
class WebhookRouteDeps:
    auth: RequestAuthService
    parser: WebhookPayloadParser
    responses: ResponseFactory
    make_dedupe_key: Callable[[dict], str]
    record_webhook_event: Callable[[str, dict], bool]
    mark_webhook_event_status: Callable[..., None]
    submit_signal: Callable[[dict], Any]
    logger: Any


def create_webhook_blueprint(deps: WebhookRouteDeps) -> Blueprint:
    bp = Blueprint("webhook_routes", __name__)

    @bp.post("/webhook")
    def webhook():
        deps.auth.require_valid_secret(request)
        data = deps.parser.parse(request)
        dedupe_key = deps.make_dedupe_key(data)

        if not deps.record_webhook_event(dedupe_key, data):
            return _duplicate_response(deps, data, dedupe_key)

        data["_dedupe_key"] = dedupe_key
        try:
            deps.mark_webhook_event_status(dedupe_key, "queued")
            deps.submit_signal(data)
        except Exception as e:
            return _queue_error_response(deps, data, dedupe_key, e)

        return _received_response(deps, data)

    return bp


def _duplicate_response(deps: WebhookRouteDeps, data: dict, dedupe_key: str):
    deps.logger.warning(
        f"Duplicate webhook ignored: symbol={data['symbol']} "
        f"action={data['action']} price={data['price']} "
        f"dedupe_key={dedupe_key[:24]}..."
    )
    return deps.responses.json({
        "status": "duplicate_ignored",
        "symbol": data["symbol"],
        "action": data["action"],
        "price": data["price"],
        "timestamp": deps.responses.timestamp(),
    })


def _queue_error_response(deps: WebhookRouteDeps, data: dict, dedupe_key: str, exc: Exception):
    deps.logger.error(
        f"Failed to submit signal to executor for {data['symbol']} "
        f"{data['action'].upper()}: {exc}"
    )
    deps.mark_webhook_event_status(
        dedupe_key,
        "error",
        failure_reason=f"failed to queue signal: {exc}",
    )
    return deps.responses.json({
        "status": "error",
        "reason": "failed to queue signal",
        "symbol": data["symbol"],
        "action": data["action"],
        "price": data["price"],
        "timestamp": deps.responses.timestamp(),
    }, 503)


def _received_response(deps: WebhookRouteDeps, data: dict):
    return deps.responses.json({
        "status": "received",
        "queued": True,
        "symbol": data["symbol"],
        "action": data["action"],
        "price": data["price"],
        "timestamp": deps.responses.timestamp(),
    })
