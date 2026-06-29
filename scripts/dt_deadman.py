#!/usr/bin/env python3
"""dt_deadman.py — autonomy safety-net for DT-triggered SAFE jobs (PROPOSAL).

STAGED PROPOSAL. Destined for the bot tree at ``scripts/dt_deadman.py``, merged by a human
through the ``trading_dev``/Daedalus propose-only worktree. NOT written into the live bot
tree or its git worktree by Deep Thought.

PURPOSE — keep the bot autonomous if Deep Thought is down. Phase 2 moves the 11 SAFE jobs
from a plain cron schedule to DT-triggered. The risk: if DT never fires (host off, kill
switch engaged, network dead), those jobs silently stop. The deadman closes that gap.

HOW IT DECIDES — for a given job key it reads the bot's own ``job_runs`` ledger (read-only,
``mode=ro`` + ``PRAGMA query_only``) and asks: *has this job SUCCEEDED within its window?*
A success is a row that actually ran (``lock_acquired = 1``, no ``skipped_reason``) with
``exit_code = 0`` — matching ``job_supervisor.classify_run`` semantics EXACTLY. It counts
BOTH the cron ``job_name`` and the DT ``<name>_dt`` variant (provenance Option A), so a
DT-triggered success satisfies the deadman just as a cron success would.

  * If a fresh success exists (cron OR DT)  → exit 0, run NOTHING (DT has it covered).
  * If the window has lapsed with no success → run the SAME fixed argv the DT wrapper would,
    via ``dt_trigger`` (deny-scanned, shell=False), so the job still happens autonomously.

The deadman cron entry fires at a time AFTER the DT-preferred slot, giving DT first crack;
the deadman only acts on a miss. It is itself idempotent against the live lock (it reuses
the job's own ``--lock-file``), so a deadman run colliding with a late DT run is a no-op skip.

Stdlib only. Reads job_runs read-only; never writes the DB; never sources /etc/trading-bot.env.
"""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timedelta, timezone
from typing import Optional

# Import the wrapper as a sibling so the deadman re-uses the SAME allowlist + deny-scan.
import importlib.util

_HERE = os.path.dirname(os.path.abspath(__file__))
_spec = importlib.util.spec_from_file_location(
    "dt_trigger", os.path.join(_HERE, "dt_trigger.py"))
dt = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(dt)

DB_PATH = f"{dt.BOT_DIR}/trades.db"
TABLE = "job_runs"
TIMEOUT_EXIT_CODE = 124

# Per-job deadman freshness window (hours). A job is "covered" if it SUCCEEDED within this
# many hours. Sized a little longer than each job's natural cadence so a single missed DT
# slot does not trip the deadman prematurely; tune per operations experience.
WINDOW_HOURS = {
    # Family A — learning / model
    "after_close_learning": 30,          # weekday after-close → daily-ish
    "after_close_research_batch": 24 * 8,  # weekly (Sat 04:30) → ~8d
    "intraday_learning_noon": 30,        # weekday noon → daily-ish
    # Family B — event / research
    "collect_and_score_events_afterhours": 30,   # Mon–Thu 18:00
    "collect_and_score_events_friday_afterhours": 24 * 8,  # Fri 18:00 → ~weekly
    "collect_and_score_events_weekend": 24 * 4,  # Sat/Sun 10:00/18:00
    "pead_benzinga_snapshot": 30,        # weekday 18:00
    "post_earnings_drift_scan": 24 * 9,  # weekly (Sat 02:00) → ~9d
    # Family C — reporting / vault
    "daily_summary": 30,                 # weekday 16:00
    "weekly_summary": 24 * 8,            # Fri 16:05 → ~8d
    "trade_matcher": 30,                 # weekday 16:10
    "historical_bar_archive": 30,        # weekday 16:20
}


def _classify(row: Optional[dict]) -> str:
    """Mirror job_supervisor.classify_run exactly."""
    if not row:
        return "inconclusive"
    if _as_int(row.get("lock_acquired")) == 0 or (row.get("skipped_reason") not in (None, "")):
        return "skipped"
    code = _as_int(row.get("exit_code"))
    if code == TIMEOUT_EXIT_CODE:
        return "timed_out"
    if code is not None and code != 0:
        return "failed"
    return "success"


def _as_int(v):
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def _parse_iso(value) -> Optional[datetime]:
    if not value:
        return None
    try:
        ts = datetime.fromisoformat(str(value))
    except (ValueError, TypeError):
        return None
    return ts.replace(tzinfo=timezone.utc) if ts.tzinfo is None else ts


def has_fresh_success(job_key: str, *, db_path: str = DB_PATH,
                      now: Optional[datetime] = None) -> bool:
    """True if ``job_key`` SUCCEEDED within its window, counting BOTH the cron job_name and
    the DT ``_dt`` variant. Read-only; a missing/locked DB degrades to 'no fresh success'
    (fail-safe: the deadman would then RUN the job, which is the conservative choice)."""
    entry = dt.validate_job(job_key)
    base = entry["job_name"]
    names = (base, base + dt.DT_SUFFIX)
    window_h = WINDOW_HOURS.get(job_key, 30)
    cutoff = (now or datetime.now(timezone.utc)) - timedelta(hours=window_h)

    try:
        conn = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        conn.execute("PRAGMA query_only = ON")
        conn.row_factory = sqlite3.Row
        placeholders = ",".join("?" for _ in names)
        cur = conn.execute(
            f"SELECT exit_code, lock_acquired, skipped_reason, started_at "
            f"FROM {TABLE} WHERE job_name IN ({placeholders}) "
            "ORDER BY started_at DESC LIMIT 50", list(names))
        rows = [dict(r) for r in cur.fetchall()]
        conn.close()
    except sqlite3.Error:
        return False  # fail-safe: treat as "not covered" so the job still runs

    for row in rows:
        if _classify(row) != "success":
            continue
        started = _parse_iso(row.get("started_at"))
        if started is not None and started >= cutoff:
            return True
    return False


def run_deadman(job_key: str, *, now: Optional[datetime] = None,
                runner=None) -> dict:
    """If the job lacks a fresh success, dispatch it via the wrapper (same fixed argv,
    deny-scanned, shell=False). The deadman bypasses the market-hours guard (it runs on the
    bot host's own schedule, outside the live band by cron placement) but keeps the lock
    discipline — the job's own --lock-file makes a collision a clean skip.

    The market-hours guard is intentionally forced off here: the deadman cron lines are
    placed in quiet windows (mirroring the original cron times, all outside 09:00–14:59), so
    the guard would be redundant; and an autonomy net must not refuse to run because of a
    clock check. Rate-limit/idempotency are also skipped — the deadman is the bot's own
    schedule, not a model-driven trigger."""
    covered = has_fresh_success(job_key, now=now)
    if covered:
        return {"job": job_key, "action": "skip", "reason": "fresh success within window"}

    argv = dt.build_argv(job_key)
    dt.deny_scan(argv)  # defense-in-depth even on the deadman path
    run = runner or dt._real_runner
    proc = run(argv, capture_output=True, text=True)
    rc = getattr(proc, "returncode", 1)
    return {
        "job": job_key,
        "action": "ran",
        "reason": "no fresh success within window; deadman dispatched",
        "exit_code": rc,
        "dispatched": rc == 0,
    }


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dt_deadman.py",
        description="Autonomy net: run a SAFE job only if it has not succeeded in its window.")
    parser.add_argument("--job", required=True, help="one of the closed enum job keys")
    parser.add_argument("--check-only", action="store_true",
                        help="print coverage status; never run the job")
    args = parser.parse_args(argv)

    try:
        dt.validate_job(args.job)
    except dt.TriggerError as exc:
        print(json.dumps({"error": str(exc)}))
        return 2

    if args.check_only:
        covered = has_fresh_success(args.job)
        print(json.dumps({"job": args.job, "covered": covered}))
        return 0

    result = run_deadman(args.job)
    print(json.dumps(result))
    if result["action"] == "skip":
        return 0
    return int(result.get("exit_code", 1))


if __name__ == "__main__":
    sys.exit(main())
