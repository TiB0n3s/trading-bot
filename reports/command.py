"""Shared report command interface.

This package is the consolidation layer between operator commands and older
root-level report scripts. New reports should implement ``ReportCommand``
directly through services; legacy script adapters are explicitly marked here so
the remaining argv-based compatibility is centralized instead of duplicated in
one wrapper module per report.
"""

from __future__ import annotations

import importlib
import sys
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Protocol

BASE_DIR = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class ReportRequest:
    target_date: str
    options: dict[str, object] = field(default_factory=dict)


class ReportCommand(Protocol):
    name: str
    version: str
    legacy_argv_adapter: bool

    def run(self, request: ReportRequest) -> bool:
        ...


@contextmanager
def _argv(*args: str):
    old = sys.argv
    sys.argv = list(args)
    try:
        yield
    finally:
        sys.argv = old


def _ensure_base_on_path() -> None:
    if str(BASE_DIR) not in sys.path:
        sys.path.insert(0, str(BASE_DIR))


@dataclass(frozen=True)
class FunctionReportCommand:
    name: str
    runner: Callable[[ReportRequest], bool]
    version: str = "report_command_v1"
    legacy_argv_adapter: bool = False

    def run(self, request: ReportRequest) -> bool:
        return bool(self.runner(request))


@dataclass(frozen=True)
class ScriptReportCommand:
    name: str
    module_name: str
    argv_builder: Callable[[ReportRequest], list[str]]
    version: str = "legacy_script_report_adapter_v1"
    legacy_argv_adapter: bool = True

    def run(self, request: ReportRequest) -> bool:
        _ensure_base_on_path()
        mod = importlib.import_module(self.module_name)
        argv = [self.module_name, *self.argv_builder(request)]
        with _argv(*argv):
            try:
                result = mod.main()
                if isinstance(result, int):
                    return result == 0
                return True
            except SystemExit as exc:
                return exc.code == 0 or exc.code is None
