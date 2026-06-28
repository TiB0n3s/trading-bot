"""
Sequential pipeline runner for multi-step cron jobs.

Replaces fixed-time cron chains where steps depend on each other.
Each step runs in-process; the runner tracks timing and halts on
critical failures.
"""

from __future__ import annotations

import importlib
import json
import os
import resource
import signal
import subprocess
import sys
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

_EASTERN = ZoneInfo("America/New_York")


def default_market_date() -> str:
    """Today's date in US/Eastern (the bot's calendar) as YYYY-MM-DD.

    CLI --date defaults previously used naive ``date.today()``, which resolves to
    the host clock's local date (the hosts run Central) and can be off by a day
    near the CT/ET midnight boundary. Eastern is the canonical trading calendar.
    """
    return datetime.now(_EASTERN).date().isoformat()

BASE_DIR = Path(__file__).resolve().parent.parent

# Generous hang-guard for child processes spawned by pipeline jobs (retrain /
# backfill etc.). This is a backstop against an indefinitely stuck child (e.g. a
# blocked socket), NOT a work limit -- legitimate long jobs finish well within it.
# job_runner --timeout-seconds remains the primary process-group kill.
DEFAULT_CHILD_TIMEOUT_SECONDS = 14400  # 4 hours


def run_child(cmd, *, cwd: "str | Path | None" = None, timeout_seconds: int | None = None) -> int:
    """Run a child process with a generous timeout; a hang becomes a logged failure.

    Returns the child's return code, or 1 if it timed out (so callers that map a
    non-zero code to a failed job surface the hang instead of blocking forever).
    """
    if timeout_seconds is None:
        try:
            timeout_seconds = int(
                os.environ.get("OPS_PIPELINE_CHILD_TIMEOUT_SECONDS", str(DEFAULT_CHILD_TIMEOUT_SECONDS))
            )
        except (TypeError, ValueError):
            timeout_seconds = DEFAULT_CHILD_TIMEOUT_SECONDS
    try:
        return int(subprocess.run(cmd, cwd=cwd, timeout=timeout_seconds).returncode)
    except subprocess.TimeoutExpired:
        print(
            f"[ERROR] pipeline child timed out after {timeout_seconds}s: "
            f"{' '.join(str(c) for c in cmd)}"
        )
        return 1


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
    memory_limit_mb: int = 0
    timeout_seconds: int = 0
    marker_path: Path | None = None

    def should_skip(self) -> bool:
        return self.marker_path is not None and self.marker_path.exists()

    def write_marker(self, *, pipeline_name: str, target_date: str, duration_sec: float) -> None:
        if self.marker_path is None:
            return
        self.marker_path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": "pipeline_step_marker_v1",
            "pipeline_name": pipeline_name,
            "target_date": target_date,
            "step_name": self.name,
            "module": self.module,
            "argv": self.argv,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "duration_sec": duration_sec,
        }
        self.marker_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")

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
    skipped: bool = False


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

        if step.should_skip():
            print(f"[SKIP] {step.name} already completed: {step.marker_path}")
            result.steps.append(
                StepResult(
                    name=step.name,
                    ok=True,
                    duration_sec=0.0,
                    critical=step.critical,
                    skipped=True,
                )
            )
            continue

        t0 = time.monotonic()
        try:
            with _resource_limits(step.memory_limit_mb, step.timeout_seconds):
                ok = step.run()
        except Exception as exc:
            print(f"[ERROR] {step.name} raised an unhandled exception: {exc}")
            ok = False
        duration = round(time.monotonic() - t0, 2)

        if ok:
            step.write_marker(
                pipeline_name=name,
                target_date=target_date,
                duration_sec=duration,
            )

        status = "[OK]" if ok else ("[FAIL]" if step.critical else "[WARN]")
        print(f"{status} {step.name} completed in {duration}s")
        result.steps.append(
            StepResult(
                name=step.name,
                ok=ok,
                duration_sec=duration,
                critical=step.critical,
            )
        )

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


class StepTimeout(Exception):
    pass


@contextmanager
def _resource_limits(memory_limit_mb: int = 0, timeout_seconds: int = 0):
    old_limits = None
    old_alarm = None
    old_handler = None

    def _handle_timeout(signum, frame):  # noqa: ARG001
        raise StepTimeout(f"step exceeded timeout_seconds={timeout_seconds}")

    try:
        if memory_limit_mb and memory_limit_mb > 0:
            bytes_limit = int(memory_limit_mb) * 1024 * 1024
            old_limits = resource.getrlimit(resource.RLIMIT_AS)
            old_soft, old_hard = old_limits
            hard = old_hard
            if hard in (-1, resource.RLIM_INFINITY):
                hard = resource.RLIM_INFINITY
            soft = bytes_limit if hard in (-1, resource.RLIM_INFINITY) else min(bytes_limit, hard)
            resource.setrlimit(resource.RLIMIT_AS, (soft, old_hard))
            os.environ["PIPELINE_STEP_MEMORY_LIMIT_MB"] = str(memory_limit_mb)

        if timeout_seconds and timeout_seconds > 0:
            old_handler = signal.getsignal(signal.SIGALRM)
            old_alarm = signal.alarm(0)
            signal.signal(signal.SIGALRM, _handle_timeout)
            signal.alarm(int(timeout_seconds))

        yield
    finally:
        if timeout_seconds and timeout_seconds > 0:
            signal.alarm(0)
            if old_handler is not None:
                signal.signal(signal.SIGALRM, old_handler)
            if old_alarm:
                signal.alarm(old_alarm)
        if old_limits is not None:
            resource.setrlimit(resource.RLIMIT_AS, old_limits)
        os.environ.pop("PIPELINE_STEP_MEMORY_LIMIT_MB", None)
