"""Status and account HTTP routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from flask import Blueprint, request

from api.request_services import RequestAuthService, ResponseFactory


@dataclass(frozen=True)
class StatusRouteDeps:
    auth: RequestAuthService
    responses: ResponseFactory
    health_payload: Callable[[], dict]
    status_payload: Callable[[], dict]
    positions_payload: Callable[[], dict]


def create_status_blueprint(deps: StatusRouteDeps) -> Blueprint:
    bp = Blueprint("status_routes", __name__)

    @bp.get("/health")
    def health():
        return deps.responses.json(deps.health_payload())

    @bp.get("/status")
    def status():
        deps.auth.require_valid_secret(request)
        return deps.responses.json(deps.status_payload())

    @bp.get("/positions")
    def positions():
        deps.auth.require_valid_secret(request)
        return deps.responses.json(deps.positions_payload())

    return bp
