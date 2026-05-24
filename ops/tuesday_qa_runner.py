#!/usr/bin/env python3
"""
Tuesday paper-session QA automation.

Runs read-only ops checks at the important Tuesday QA windows and writes a
session log. This script does not edit cron, restart services, place orders,
or change trading behavior.

Usage:
  python3 ops/tuesday_qa_runner.py --date 2026-05-26
  python3 ops/tuesday_qa_runner.py --date 2026-05-26 --dry-run
  python3 ops/tuesday_qa_runner.py --date 2026-05-26 --run-due-only
"""

from __future__ import annotations

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, date, time as dtime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

ROOT = Path(__file__).resolve().parents[1]
LOG_DIR = ROOT / "ops" / "qa_logs"
CENTRAL = ZoneInfo("America/Chicago")


@dataclass(frozen=True)
class CheckWindow:
    name: str
    at_ct: dtime
    commands: tuple[tuple[str, ...], ...]
    notes: str = ""


def qa_windows(target_date: str) -> list[CheckWindow]:
    return [
        CheckWindow(
            name="before_0800_readiness",
            at_ct=dtime(7, 45),
            commands=(
                ("git", "status", "--short"),
                (sys.executable, "run_tests.py"),
                (sys.executable, "ops_check.py", "market-context-check"),
                (sys.executable, "ops_check.py", "intelligence-summary", target_date),
                (sys.executable, "ops_check.py", "dataset-health", target_date),
                (sys.executable, "ops_check.py", "feature-health", target_date),
            ),
            notes="Pre-session readiness. Feature/label tables may be zero after DB rebuild.",
        ),
        CheckWindow(
            name="after_0800_premarket_context",
            at_ct=dtime(8, 10),
            commands=(
                (sys.executable, "ops_check.py", "market-context-check"),
                (sys.executable, "ops_check.py", "intelligence-summary", target_date),
                (sys.executable, "ops_check.py", "dataset-health", target_date),
            ),
            notes="Confirms deterministic premarket/context and 8:05 event/prediction path.",
        ),
        CheckWindow(
            name="market_open_initial",
            at_ct=dtime(8, 40),
            commands=(
                (sys.executable, "ops_check.py", "premarket"),
                (sys.executable, "ops_check.py", "feature-watch", target_date),
                (sys.executable, "ops_check.py", "rejection-summary", target_date),
                (sys.executable, "ops_check.py", "order-health", target_date),
            ),
            notes="First open-market check. Snapshots should start becoming nonzero.",
        ),
        CheckWindow(
            name="label_window",
            at_ct=dtime(10, 20),
            commands=(
                (sys.executable, "ops_check.py", "feature-watch", target_date),
                (sys.executable, "ops_check.py", "dataset-health", target_date),
                (sys.executable, "ops_check.py", "rejection-summary", target_date),
                (sys.executable, "ops_check.py", "order-health", target_date),
            ),
            notes="First useful label-health window after the 35-minute label delay.",
        ),
        CheckWindow(
            name="midday",
            at_ct=dtime(12, 0),
            commands=(
                (sys.executable, "ops_check.py", "feature-watch", target_date),
                (sys.executable, "ops_check.py", "rejection-summary", target_date),
                (sys.executable, "ops_check.py", "order-health", target_date),
                (sys.executable, "ops_check.py", "positions"),
            ),
            notes="Midday feature/order/rejection/position state.",
        ),
        CheckWindow(
            name="near_close",
            at_ct=dtime(14, 50),
            commands=(
                (sys.executable, "ops_check.py", "positions"),
                (sys.executable, "ops_check.py", "order-health", target_date),
                (sys.executable, "ops_check.py", "rejection-summary", target_date),
                (sys.executable, "ops_check.py", "feature-watch", target_date),
            ),
            notes="Near-close reconciliation and feature backlog check.",
        ),
        CheckWindow(
            name="after_close",
            at_ct=dtime(16, 45),
            commands=(
                (sys.executable, "ops_check.py", "dataset-health", target_date),
                (sys.executable, "ops_check.py", "feature-watch", target_date),
                (sys.executable, "ops_check.py", "rejection-summary", target_date),
                (sys.executable, "ops_check.py", "order-health", target_date),
                (sys.executable, "ops_check.py", "post", target_date),
            ),
            notes="After-close evidence after scheduled learning/reporting jobs have had time to run.",
        ),
    ]


def target_dt(target_date: str, at_ct: dtime) -> datetime:
    day = date.fromisoformat(target_date)
    return datetime.combine(day, at_ct, tzinfo=CENTRAL)


def open_log(target_date: str, dry_run: bool) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    suffix = "dry_run" if dry_run else "run"
    stamp = datetime.now(CENTRAL).strftime("%Y%m%d_%H%M%S")
    return LOG_DIR / f"tuesday_qa_{target_date}_{stamp}_{suffix}.log"


def write(log_file: Path, message: str) -> None:
    print(message, flush=True)
    with log_file.open("a") as f:
        f.write(message + "\n")


def run_command(cmd: tuple[str, ...], log_file: Path) -> int:
    write(log_file, "")
    write(log_file, "+ " + " ".join(cmd))
    started = datetime.now(CENTRAL)
    proc = subprocess.run(
        list(cmd),
        cwd=ROOT,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.STDOUT,
        timeout=300,
    )
    duration = (datetime.now(CENTRAL) - started).total_seconds()
    if proc.stdout:
        for line in proc.stdout.rstrip().splitlines():
            write(log_file, line)
    write(log_file, f"[exit={proc.returncode} duration={duration:.1f}s]")
    return proc.returncode


def due_windows(windows: list[CheckWindow], target_date: str, run_due_only: bool) -> list[CheckWindow]:
    if not run_due_only:
        return windows
    now = datetime.now(CENTRAL)
    return [w for w in windows if target_dt(target_date, w.at_ct) <= now]


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--date", required=True, help="Market date, e.g. 2026-05-26")
    parser.add_argument("--dry-run", action="store_true", help="Print schedule without running checks")
    parser.add_argument("--run-due-only", action="store_true", help="Run only windows whose scheduled time has already passed")
    parser.add_argument("--no-sleep", action="store_true", help="Run selected windows immediately without waiting")
    args = parser.parse_args()

    windows = due_windows(qa_windows(args.date), args.date, args.run_due_only)
    log_file = open_log(args.date, args.dry_run)

    write(log_file, "=" * 80)
    write(log_file, f"Tuesday QA runner started: {datetime.now(CENTRAL).isoformat()}")
    write(log_file, f"target_date={args.date} dry_run={args.dry_run} run_due_only={args.run_due_only} no_sleep={args.no_sleep}")
    write(log_file, f"repo={ROOT}")
    write(log_file, f"log_file={log_file}")
    write(log_file, "=" * 80)

    if not windows:
        write(log_file, "No QA windows selected.")
        return 0

    failures = 0

    for window in windows:
        scheduled = target_dt(args.date, window.at_ct)
        now = datetime.now(CENTRAL)
        wait_seconds = (scheduled - now).total_seconds()

        write(log_file, "")
        write(log_file, "-" * 80)
        write(log_file, f"Window: {window.name}")
        write(log_file, f"Scheduled CT: {scheduled.isoformat()}")
        write(log_file, f"Notes: {window.notes}")

        if args.dry_run:
            for cmd in window.commands:
                write(log_file, "  would run: " + " ".join(cmd))
            continue

        if wait_seconds > 0 and not args.no_sleep:
            write(log_file, f"Sleeping {wait_seconds:.0f}s until window...")
            time.sleep(wait_seconds)

        write(log_file, f"Running window at {datetime.now(CENTRAL).isoformat()}")
        for cmd in window.commands:
            try:
                rc = run_command(cmd, log_file)
            except subprocess.TimeoutExpired:
                write(log_file, "[FAIL] command timed out after 300s")
                rc = 124
            except Exception as exc:
                write(log_file, f"[FAIL] command raised: {exc}")
                rc = 1
            if rc != 0:
                failures += 1

    write(log_file, "")
    write(log_file, "=" * 80)
    write(log_file, f"Tuesday QA runner finished: {datetime.now(CENTRAL).isoformat()}")
    write(log_file, f"command_failures={failures}")
    write(log_file, "=" * 80)

    return 0 if failures == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
