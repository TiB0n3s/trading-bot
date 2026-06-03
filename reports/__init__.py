"""Report command registry package.

Operator-facing report commands are exposed through ``reports.registry``.
Legacy root-level report scripts remain as compatibility entrypoints, but
ops/report orchestration should use the registry so report execution is
centralized and testable.
"""

from reports.command import ReportCommand, ReportRequest
from reports.registry import get_report_commands, run_report

__all__ = [
    "ReportCommand",
    "ReportRequest",
    "get_report_commands",
    "run_report",
]
