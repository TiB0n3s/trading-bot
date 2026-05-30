"""Blueprint registration for the Flask application."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from flask import Flask

from api.debug_routes import DebugRouteDeps, create_debug_blueprint
from api.request_services import RequestAuthService, ResponseFactory, WebhookPayloadParser
from api.status_routes import StatusRouteDeps, create_status_blueprint
from api.webhook_routes import WebhookRouteDeps, create_webhook_blueprint


@dataclass(frozen=True)
class RouteRegistrationDeps:
    validate_secret: Callable[[Any], None]
    approved_symbols: set[str]
    price_ranges: dict[str, tuple[float, float]]
    logger: Any
    make_dedupe_key: Callable[[dict[str, Any]], str]
    record_webhook_event: Callable[[str, dict[str, Any]], bool]
    mark_webhook_event_status: Callable[..., Any]
    submit_signal: Callable[[dict[str, Any]], Any]
    health_payload: Callable[[], dict[str, Any]]
    status_payload: Callable[[], dict[str, Any]]
    positions_payload: Callable[[], dict[str, Any]]
    debug_symbol_payload: Callable[[str], Any]


def register_routes(flask_app: Flask, deps: RouteRegistrationDeps) -> None:
    """Register HTTP blueprints against a Flask app instance."""
    auth = RequestAuthService(validate_secret=deps.validate_secret)
    responses = ResponseFactory()

    flask_app.register_blueprint(
        create_webhook_blueprint(
            WebhookRouteDeps(
                auth=auth,
                parser=WebhookPayloadParser(
                    deps.approved_symbols,
                    deps.price_ranges,
                    deps.logger,
                ),
                responses=responses,
                make_dedupe_key=deps.make_dedupe_key,
                record_webhook_event=deps.record_webhook_event,
                mark_webhook_event_status=deps.mark_webhook_event_status,
                submit_signal=deps.submit_signal,
                logger=deps.logger,
            )
        )
    )
    flask_app.register_blueprint(
        create_status_blueprint(
            StatusRouteDeps(
                auth=auth,
                responses=responses,
                health_payload=deps.health_payload,
                status_payload=deps.status_payload,
                positions_payload=deps.positions_payload,
            )
        )
    )
    flask_app.register_blueprint(
        create_debug_blueprint(
            DebugRouteDeps(
                auth=auth,
                responses=responses,
                debug_symbol_payload=deps.debug_symbol_payload,
            )
        )
    )
