"""Debug HTTP routes."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from flask import Blueprint, request

from api.request_services import RequestAuthService, ResponseFactory


@dataclass(frozen=True)
class DebugRouteDeps:
    auth: RequestAuthService
    responses: ResponseFactory
    debug_symbol_payload: Callable[[str], tuple[dict, int]]


def create_debug_blueprint(deps: DebugRouteDeps) -> Blueprint:
    bp = Blueprint("debug_routes", __name__)

    @bp.get("/debug/symbol/<symbol>")
    def debug_symbol(symbol):
        deps.auth.require_valid_secret(request)
        payload, status = deps.debug_symbol_payload(symbol)
        return deps.responses.json(payload, status)

    return bp
