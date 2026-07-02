"""Operator checks for installed scheduler drift."""

from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class CronDrift:
    missing: list[str]
    extra: list[str]

    @property
    def ok(self) -> bool:
        return not self.missing and not self.extra


def _command_lines(text: str) -> list[str]:
    lines = []
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def compare_crontabs(reference_text: str, installed_text: str) -> CronDrift:
    reference = _command_lines(reference_text)
    installed = _command_lines(installed_text)
    reference_counts = {line: reference.count(line) for line in set(reference)}
    installed_counts = {line: installed.count(line) for line in set(installed)}

    missing = []
    extra = []
    for line, count in sorted(reference_counts.items()):
        missing.extend([line] * max(0, count - installed_counts.get(line, 0)))
    for line, count in sorted(installed_counts.items()):
        extra.extend([line] * max(0, count - reference_counts.get(line, 0)))
    return CronDrift(missing=missing, extra=extra)


def _installed_crontab() -> tuple[bool, str]:
    result = subprocess.run(
        ["crontab", "-l"],
        text=True,
        capture_output=True,
        timeout=5,
        check=False,
    )
    if result.returncode != 0:
        return False, (result.stderr or result.stdout or "").strip()
    return True, result.stdout


def run_scheduler_drift_report(*, base_dir: Path) -> bool:
    reference_path = base_dir / "ops" / "crontab.tradingbot.current.txt"

    print()
    print("=" * 72)
    print("  Scheduler Drift")
    print("=" * 72)
    print("report_version          : scheduler_drift_v1")
    print("runtime_effect          : diagnostic_only_no_runtime_change")
    print(f"reference_crontab       : {reference_path}")

    if not reference_path.exists():
        print("[FAIL] checked-in crontab reference is missing")
        return False

    ok, installed = _installed_crontab()
    if not ok:
        print("[FAIL] could not read installed user crontab")
        print(f"detail                  : {installed or '-'}")
        return False

    drift = compare_crontabs(reference_path.read_text(), installed)
    print(f"missing_lines           : {len(drift.missing)}")
    print(f"extra_lines             : {len(drift.extra)}")

    if drift.missing:
        print()
        print("Missing installed lines")
        for line in drift.missing:
            print(f"  - {line}")
    if drift.extra:
        print()
        print("Extra installed lines")
        for line in drift.extra:
            print(f"  - {line}")

    print()
    if drift.ok:
        print("[OK] installed crontab matches checked-in command lines")
        return True
    print("[FAIL] installed crontab differs from checked-in command lines")
    return False
