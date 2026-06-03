"""
Sequential pipeline runner for multi-step cron jobs.

Replaces fixed-time cron chains where steps depend on each other.
Each step runs in-process; the runner tracks timing and halts on
critical failures.
"""

from __future__ import annotations

import importlib
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

BASE_DIR = Path(__file__).resolve().parent.parent


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


@dataclass
class Step:
    name: str
    module: str
    argv: list[str]
    critical: bool = True
    description: str = ""

    def run(self) -> bool:
        _ensure_base_on_path()
        mod = importlib.import_module(self.module)
        with _argv(self.module, *self.argv):
            try:
                result = mod.main()
                if isinstance(result, int):
                    return result == 0
                return True
            except SystemExit as exc:
                code = exc.code
                return code == 0 or code is None


@dataclass
class StepResult:
    name: str
    ok: bool
    duration_sec: float
    critical: bool


@dataclass
class PipelineResult:
    pipeline_name: str
    target_date: str
    steps: list[StepResult] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return all(r.ok for r in self.steps if r.critical)

    @property
    def total_duration_sec(self) -> float:
        return sum(r.duration_sec for r in self.steps)


def run_pipeline(
    name: str,
    steps: list[Step],
    target_date: str,
    *,
    stop_on_critical_failure: bool = True,
) -> PipelineResult:
    """Run pipeline steps in order; return a result summary."""
    _HR = "=" * 72
    result = PipelineResult(pipeline_name=name, target_date=target_date)

    print()
    print(_HR)
    print(f"  Pipeline: {name}  [{target_date}]")
    print(_HR)

    for step in steps:
        label = f"  Step: {step.name}"
        if step.description:
            label += f"  — {step.description}"
        print()
        print(label)
        print("-" * 72)

        t0 = time.monotonic()
        try:
            ok = step.run()
        except Exception as exc:
            print(f"[ERROR] {step.name} raised an unhandled exception: {exc}")
            ok = False
        duration = round(time.monotonic() - t0, 2)

        status = "[OK]" if ok else ("[FAIL]" if step.critical else "[WARN]")
        print(f"{status} {step.name} completed in {duration}s")
        result.steps.append(StepResult(
            name=step.name,
            ok=ok,
            duration_sec=duration,
            critical=step.critical,
        ))

        if not ok and step.critical and stop_on_critical_failure:
            print(f"\n[PIPELINE HALTED] critical step '{step.name}' failed")
            break

    print()
    print(_HR)
    total = result.total_duration_sec
    if result.ok:
        print(f"[OK] {name} pipeline completed in {total:.1f}s")
    else:
        failed = [r.name for r in result.steps if not r.ok]
        print(f"[FAIL] {name} pipeline failed — steps: {', '.join(failed)} (total {total:.1f}s)")

    return result
