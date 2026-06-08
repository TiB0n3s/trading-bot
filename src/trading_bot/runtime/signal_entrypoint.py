"""Runtime signal entrypoint helpers for the deployed compatibility module."""

from __future__ import annotations

from typing import Any


def build_signal_pipeline(runtime_module: Any, app_container: Any | None = None) -> Any:
    app_container = app_container or runtime_module.container
    return app_container.build_signal_pipeline(runtime=runtime_module)


def process_signal(runtime_module: Any, data: dict[str, Any]) -> Any:
    return build_signal_pipeline(runtime_module).run(data)
