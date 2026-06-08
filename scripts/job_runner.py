#!/usr/bin/env python3
"""Run a cron/operator job with durable job_runs ledger persistence."""

from __future__ import annotations

import argparse
import fcntl
import re
import subprocess
import sys
import time
from pathlib import Path

from repositories.job_runs_repo import JobRunsRepository
from services.job_runs_service import JobRunsService, _now_iso, build_default_job_runs_service


def _append_log(path: str | None, message: str) -> None:
    if not path:
        print(message)
        return
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a") as fh:
        fh.write(message.rstrip() + "\n")


ROW_COUNT_PATTERNS = [
    re.compile(r"\brows_written\s*[:=]\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\brows?\s+(?:written|inserted|updated|created)\s*[:=]\s*(\d+)\b", re.IGNORECASE),
    re.compile(r"\bInserted\s+(\d+)\s+(?:[\w_]+\s+)?rows?\b", re.IGNORECASE),
    re.compile(r"\bApplied\s+event\s+aggregates.*\bupdated=(\d+)\b", re.IGNORECASE),
    re.compile(
        r"\bPoll\s+complete\s+-\s+checked:\s*\d+,\s+updated:\s*(\d+),\s+skipped:\s*\d+\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bWrote\s+refreshed\s+market_context\.json\s+\((\d+)\s+symbols\)", re.IGNORECASE),
    re.compile(r"\bsuccess(?:ful)?\s*[:=]\s*(\d+)\b", re.IGNORECASE),
]


def _log_size(log_file: str | None) -> int:
    if not log_file:
        return 0
    p = Path(log_file)
    if not p.exists():
        return 0
    try:
        return p.stat().st_size
    except OSError:
        return 0


def _read_log_tail(log_file: str | None, start_offset: int) -> str:
    if not log_file:
        return ""
    p = Path(log_file)
    if not p.exists():
        return ""
    try:
        with p.open("r", errors="replace") as fh:
            fh.seek(start_offset)
            return fh.read()
    except OSError:
        return ""


def _infer_rows_written(output: str) -> int | None:
    matches: list[int] = []
    for pattern in ROW_COUNT_PATTERNS:
        for match in pattern.finditer(output or ""):
            try:
                matches.append(int(match.group(1)))
            except Exception:
                pass
    if matches:
        return max(matches)
    return None


def _infer_warnings_count(output: str) -> int:
    warnings = 0
    for line in (output or "").splitlines():
        text = line.lower()
        if "warning" in text or "[warn]" in text or " warn " in f" {text} ":
            warnings += 1
    return warnings


def _run_command(command: list[str], log_file: str | None) -> int:
    if log_file:
        p = Path(log_file)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open("a") as fh:
            result = subprocess.run(command, stdout=fh, stderr=subprocess.STDOUT)
            return result.returncode

    result = subprocess.run(command)
    return result.returncode


def _parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--job-name", required=True)
    parser.add_argument("--lock-file")
    parser.add_argument("--log-file")
    parser.add_argument("--rows-written", type=int)
    parser.add_argument("--warnings-count", type=int)
    parser.add_argument("--artifact-path")
    parser.add_argument("--db-path")
    parser.add_argument("command", nargs=argparse.REMAINDER)
    args = parser.parse_args(argv)

    if args.command and args.command[0] == "--":
        args.command = args.command[1:]
    if not args.command:
        parser.error("command is required after --")
    return args


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv or sys.argv[1:])
    service = (
        JobRunsService(JobRunsRepository(args.db_path))
        if args.db_path
        else build_default_job_runs_service()
    )
    started_at = _now_iso()
    started_monotonic = time.monotonic()

    lock_handle = None
    if args.lock_file:
        lock_path = Path(args.lock_file)
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        lock_handle = lock_path.open("w")
        try:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            message = f"{_now_iso()} lock-busy: {args.job_name} skipped"
            _append_log(args.log_file, message)
            record = service.build_record(
                job_name=args.job_name,
                started_at=started_at,
                started_monotonic=started_monotonic,
                exit_code=None,
                lock_acquired=False,
                skipped_reason="lock_busy",
                rows_written=args.rows_written,
                warnings_count=args.warnings_count,
                artifact_path=args.artifact_path,
                command=args.command,
            )
            service.record_run(record)
            return 0

    _append_log(args.log_file, f"{_now_iso()} job-start: {args.job_name}")
    log_start_offset = _log_size(args.log_file)
    exit_code = 1
    try:
        exit_code = _run_command(args.command, args.log_file)
        return exit_code
    finally:
        _append_log(
            args.log_file, f"{_now_iso()} job-finish: {args.job_name} exit_code={exit_code}"
        )
        output = _read_log_tail(args.log_file, log_start_offset)
        rows_written = (
            args.rows_written if args.rows_written is not None else _infer_rows_written(output)
        )
        warnings_count = (
            args.warnings_count
            if args.warnings_count is not None
            else _infer_warnings_count(output)
        )
        record = service.build_record(
            job_name=args.job_name,
            started_at=started_at,
            started_monotonic=started_monotonic,
            exit_code=exit_code,
            lock_acquired=True,
            rows_written=rows_written,
            warnings_count=warnings_count,
            artifact_path=args.artifact_path,
            command=args.command,
        )
        service.record_run(record)
        if lock_handle is not None:
            fcntl.flock(lock_handle.fileno(), fcntl.LOCK_UN)
            lock_handle.close()


if __name__ == "__main__":
    raise SystemExit(main())
