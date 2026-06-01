"""Checks that scheduled jobs use the durable job_runs runner."""

from __future__ import annotations

from pathlib import Path


LOG_LEDGER_CONSISTENCY_REPORT_VERSION = "log_ledger_consistency_v1"


def _cron_lines(path: Path) -> list[str]:
    if not path.exists():
        return []
    lines = []
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lines.append(line)
    return lines


def run_log_ledger_consistency(*, base_dir: Path) -> bool:
    print()
    print("=" * 72)
    print("  Log-to-Ledger Consistency")
    print("=" * 72)
    print(f"report_version          : {LOG_LEDGER_CONSISTENCY_REPORT_VERSION}")

    cron_path = base_dir / "ops" / "crontab.tradingbot.current.txt"
    lines = _cron_lines(cron_path)
    if not lines:
        print(f"[WARN] no cron entries found at {cron_path}")
        return False

    scheduled = [line for line in lines if not line.startswith(("MAILTO=", "SHELL=", "PATH="))]
    runner_lines = [line for line in scheduled if "job_runner.py" in line]
    unwrapped = [line for line in scheduled if "job_runner.py" not in line]
    missing_lock = [line for line in runner_lines if "--lock-file" not in line]
    missing_log = [line for line in runner_lines if "--log-file" not in line]

    print(f"scheduled_entries : {len(scheduled)}")
    print(f"job_runner_entries: {len(runner_lines)}")
    print(f"unwrapped_entries : {len(unwrapped)}")
    print(f"missing_lock_file : {len(missing_lock)}")
    print(f"missing_log_file  : {len(missing_log)}")

    if unwrapped:
        print()
        print("Unwrapped scheduled entries:")
        for line in unwrapped[:12]:
            print(f"  {line}")

    if missing_lock:
        print()
        print("job_runner entries without --lock-file:")
        for line in missing_lock[:12]:
            print(f"  {line}")

    if missing_log:
        print()
        print("job_runner entries without --log-file:")
        for line in missing_log[:12]:
            print(f"  {line}")

    ok = not unwrapped and not missing_lock and not missing_log
    print()
    print("[OK] scheduled jobs are wrapped by job_runner.py" if ok else "[WARN] scheduled jobs can bypass the durable ledger")
    return ok
