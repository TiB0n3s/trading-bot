"""Flask app factory helpers.

This module owns Flask app construction and route registration mechanics. The
current root ``app.py`` remains the runtime compatibility module for signal
processing and status payload context during Phase 2 cleanup.
"""

from __future__ import annotations

from types import ModuleType
from typing import Any

from flask import Flask

from api.register_routes import RouteRegistrationDeps, register_routes
from services.debug_symbol_service import build_debug_symbol_payload
from services.positions_service import build_positions_payload
from services.status_service import build_health_payload, build_status_payload


def register_runtime_routes(
    flask_app: Flask,
    *,
    runtime_module: ModuleType,
    app_container: Any,
) -> None:
    """Register public routes against the existing runtime module context."""
    register_routes(
        flask_app,
        RouteRegistrationDeps(
            validate_secret=runtime_module.validate_secret,
            approved_symbols=runtime_module.APPROVED_SYMBOLS,
            price_ranges=runtime_module.PRICE_RANGES,
            logger=runtime_module.logger,
            submit_signal=lambda data: app_container.signal_executor_factory().submit(
                runtime_module.process_signal,
                data,
            ),
            health_payload=lambda: build_health_payload(runtime_module),
            status_payload=lambda: build_status_payload(runtime_module),
            positions_payload=lambda: build_positions_payload(runtime_module),
            debug_symbol_payload=lambda symbol: build_debug_symbol_payload(
                runtime_module,
                symbol,
            ),
        ),
    )


def create_runtime_flask_app(
    *,
    import_name: str,
    runtime_module: ModuleType,
    app_container: Any,
    run_startup: bool = False,
) -> Flask:
    """Create a Flask app using the existing runtime compatibility module."""
    if run_startup:
        runtime_module.run_startup_tasks(app_container)
    flask_app = Flask(import_name)
    flask_app.extensions["application_container"] = app_container
    register_runtime_routes(
        flask_app,
        runtime_module=runtime_module,
        app_container=app_container,
    )
    return flask_app
