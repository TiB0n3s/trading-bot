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


class ResponseFactory:
    def json(self, payload: dict, status: int = 200):
        return jsonify(payload), status

    def timestamp(self) -> str:
        return datetime.now().isoformat()
