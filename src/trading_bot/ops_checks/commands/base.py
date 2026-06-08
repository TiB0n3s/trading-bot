"""Shared command-spec primitives for ops-check command groups."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable, Mapping

HandlerMap = Mapping[str, Callable[..., bool]]


@dataclass(frozen=True)
class OpsCommandSpec:
    command: str
    handler_name: str
    arg_tokens: tuple[str, ...] = ("target_date",)

    def run(self, handlers: HandlerMap, args: Mapping[str, object]) -> bool:
        handler = handlers[self.handler_name]
        resolved_args = [args[token] for token in self.arg_tokens]
        return bool(handler(*resolved_args))


def spec(
    command: str,
    handler_name: str | None = None,
    *arg_tokens: str,
) -> OpsCommandSpec:
    return OpsCommandSpec(
        command=command,
        handler_name=handler_name or command.replace("-", "_"),
        arg_tokens=tuple(arg_tokens) or ("target_date",),
    )


def noarg(command: str, handler_name: str | None = None) -> OpsCommandSpec:
    return OpsCommandSpec(
        command=command,
        handler_name=handler_name or command.replace("-", "_"),
        arg_tokens=(),
    )
