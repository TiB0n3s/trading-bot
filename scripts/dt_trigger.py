#!/usr/bin/env python3
"""dt_trigger.py — Deep Thought → trading-bot SAFE-job trigger wrapper (PROPOSAL).

STAGED PROPOSAL. Destined for the bot tree at ``scripts/dt_trigger.py``, merged by a
human through the ``trading_dev``/Daedalus propose-only worktree. NOT written into the
live bot tree or its git worktree by Deep Thought. See ``MERGE.md``.

This is the *only* component that knows the real argv per enum (contract §2). It is the
allowlist-by-construction: a CLOSED enum of 12 SAFE job keys maps to FIXED argv lists
copied VERBATIM from the live crontab. The caller chooses only an enum key plus a strict,
typed set of params; there is no path from "enum + params" to an arbitrary command.

Hard guarantees (contract §2, threat model §5/§6):
  * ``shell=False`` always — the argv is a Python list. The only shell that ever exists is
    *inside the bot-owned fixed command string* (``bash -lc 'set -a && . /etc/trading-bot.env
    …'``) reproduced verbatim from cron; NO caller param is ever substituted into it.
  * A validated ``--date`` is passed as a SEPARATE argv element to the leaf python, never
    spliced into the ``bash -lc`` text. ``--phase`` is fixed to ``noon`` in the fixed argv.
  * Deny-scan backstop runs on the RESOLVED argv (defense-in-depth): hard-abort if it
    contains any execution / feature-gen / promotion token.
  * A ``_dt`` suffix is stamped onto ``--job-name`` for provenance (contract §4 Option A).
  * Market-hours guard + per-family rate-limit + idempotency (contract §5 / threat model §6).

Stdlib only — runs under the bot venv with no extra deps. Read-only toward the bot beyond
the job_runner invocation the caller explicitly authorized; never sources /etc/trading-bot.env.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
from datetime import date, datetime
from typing import Callable, Optional

# --------------------------------------------------------------------------- constants
BOT_DIR = "/home/tradingbot/trading-bot"
PY = f"{BOT_DIR}/venv/bin/python"
JOB_RUNNER = "scripts/job_runner.py"

# Provenance suffix (contract §4 Option A). Applied to --job-name in the fixed argv so it
# is part of the allowlist, NOT caller-controlled. Reconciliation filters on job_name = '<name>_dt'.
DT_SUFFIX = "_dt"

# Per-family hourly rate caps (contract §5 / threat model §6). A trigger over its family's
# cap inside the window is refused. Tunable; conservative defaults.
RATE_LIMIT_PER_HOUR = {"learning": 4, "research": 4, "reporting": 6}

# Idempotency / rate-limit ledger (local to the bot host; survives across invocations).
# A JSON file under the bot dir's tmp; created lazily, never touches trades.db.
_LEDGER_PATH = "/tmp/tradingbot_dt_trigger_ledger.json"
_IDEMPOTENCY_WINDOW_SEC = 3600

# Market-hours guard. The crontab's live trading-loop band is 09:00–14:xx Mon–Fri
# (auto_buy/position_manager/feature-gen run every 2–5 min there, serializing trades.db
# writes). DB-writing safe jobs MUST NOT be triggered into that window (threat model §6).
# Hours are evaluated in the bot host's local tz (the tz cron uses).
_MARKET_OPEN_HOUR = 9
_MARKET_CLOSE_HOUR = 15  # exclusive upper bound: 09:00–14:59 is the guarded band

# Param validators (contract §2.4): strict allow-lists.
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
_IDEMPOTENCY_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

# Deny-scan tokens (contract §2.5 / threat model §5). Run on the RESOLVED argv joined as
# text. Any hit ⇒ hard-abort, no exec. Mirrors DT's read-side fail-closed stamp check.
DENY_TOKENS = (
    "auto_buy",
    "run_position_manager",
    "position_momentum",
    "portfolio_rotation",
    "fill_poller",
    # feature-generation entrypoints
    "run_live_features",
    "run_label_features",
    "rolling_momentum",
    "session_momentum",
    # model promotion
    "registry",
    "promote",
    # live execution flag
    "--live",
)


class TriggerError(Exception):
    """A trigger was refused before any job_runner.py invocation."""


# --------------------------------------------------------------------------- the allowlist
# Each entry: family + the FIXED tail argv AFTER the job_runner.py program name, i.e.
#   ["--job-name", "<name>", <lock/throttle flags...>, "--", <fixed command...>]
# copied VERBATIM from the live crontab (`crontab -l`, read-only). ``writes_db`` marks a
# safe job whose leaf writes trades.db (guarded harder by market-hours). ``date_param``
# names the leaf flag a validated --date slots into (separate argv element), or None.
#
# The bot-owned inner command string (`bash -lc 'set -a && . /etc/trading-bot.env …'`) is
# reproduced verbatim; DT never composes or sources it. Where a date is parameterizable the
# server-side `$(date …)` form is kept as the default and ONLY overridden by appending a
# validated `--date <YYYY-MM-DD>` as a trailing argv element to the python leaf (it wins over
# the in-string default for argparse leaves; see param note below).

# Common bot-owned env preamble used by most lines, verbatim from cron.
_ENV = "set -a && . /etc/trading-bot.env && set +a && "


def _entry(family, job_name, flags, command, *, writes_db=False, date_param=None):
    return {
        "family": family,
        "job_name": job_name,
        "flags": list(flags),
        "command": list(command),
        "writes_db": writes_db,
        "date_param": date_param,
    }


# NOTE on log files: the live cron lines carry --log-file <path>. The wrapper reproduces
# each verbatim so the DT-triggered run logs alongside the cron run. (Log paths are bot-owned
# constants, never caller params.)
ALLOWLIST = {
    # ---- Family A — learning / model -------------------------------------------------
    "after_close_learning": _entry(
        "learning", "run_after_close_learning",
        ["--lock-file", "/tmp/tradingbot_after_close.lock",
         "--log-file", f"{BOT_DIR}/after_close_learning.log"],
        ["--", "bash", f"{BOT_DIR}/run_after_close_learning.sh"],
    ),
    "after_close_research_batch": _entry(
        "research", "after_close_research_batch",
        ["--lock-file", "/tmp/tradingbot_after_close.lock",
         "--log-file", f"{BOT_DIR}/after_close_research.log",
         "--timeout-seconds", "14400", "--ionice-idle", "--nice", "10"],
        ["--", "bash", "-lc",
         _ENV + 'TARGET_DATE=$(date -d yesterday +%F) && '
         f'{PY} pipeline/after_close_learning.py --lane research --date "$TARGET_DATE"'],
        date_param=None,  # date stays server-side ($(date -d yesterday)); not exposed
    ),
    "intraday_learning_noon": _entry(
        "learning", "noon_intraday_learning",
        ["--lock-file", "/tmp/tradingbot_noon_intraday_learning.lock",
         "--log-file", f"{BOT_DIR}/noon_intraday_learning.log"],
        ["--", "bash", "-lc",
         _ENV + f'{PY} pipeline/intraday_learning.py --date "$(date +%F)" --phase noon'],
        date_param=None,  # --phase FIXED to noon; date server-side
    ),

    # ---- Family B — event / research -------------------------------------------------
    "collect_and_score_events_afterhours": _entry(
        "research", "collect_and_score_events_afterhours",
        ["--lock-file", "/tmp/tradingbot_event_collection.lock",
         "--log-file", f"{BOT_DIR}/event_collection.log"],
        ["--", "bash", "-lc",
         _ENV + f'TARGET_DATE=$({PY} scripts/next_trading_date.py) && '
         f'{PY} scripts/collect_and_score_events.py --date "$TARGET_DATE" '
         "--max-per-symbol 2 --include-context-symbols --apply-context --predict "
         "--ai-interpret-events --ai-event-provider hybrid "
         '--output /tmp/events_"$TARGET_DATE"_afterhours.json'],
    ),
    "collect_and_score_events_friday_afterhours": _entry(
        "research", "collect_and_score_events_friday_afterhours",
        ["--lock-file", "/tmp/tradingbot_event_collection.lock",
         "--log-file", f"{BOT_DIR}/event_collection.log"],
        ["--", "bash", "-lc",
         _ENV + f'TARGET_DATE=$({PY} scripts/next_trading_date.py) && '
         f'{PY} scripts/collect_and_score_events.py --date "$TARGET_DATE" '
         "--max-per-symbol 2 --include-context-symbols --apply-context --predict "
         "--ai-interpret-events --ai-event-provider hybrid "
         '--output /tmp/events_"$TARGET_DATE"_friday_afterhours.json'],
    ),
    "collect_and_score_events_weekend": _entry(
        "research", "collect_and_score_events_weekend",
        ["--lock-file", "/tmp/tradingbot_event_collection.lock",
         "--log-file", f"{BOT_DIR}/event_collection.log"],
        ["--", "bash", "-lc",
         _ENV + f'TARGET_DATE=$({PY} scripts/next_trading_date.py) && '
         f'{PY} scripts/collect_and_score_events.py --date "$TARGET_DATE" '
         "--max-per-symbol 2 --include-context-symbols --apply-context --predict "
         "--ai-interpret-events --ai-event-provider hybrid "
         '--output /tmp/events_"$TARGET_DATE"_weekend.json'],
    ),
    "pead_benzinga_snapshot": _entry(
        "research", "pead_benzinga_snapshot",
        ["--lock-file", "/tmp/tradingbot_pead_snapshot.lock",
         "--log-file", f"{BOT_DIR}/pead_snapshot.log"],
        ["--", "bash", "-lc",
         _ENV + f'{PY} scripts/pead_benzinga_snapshot.py --lookback-days 5'],
    ),
    "post_earnings_drift_scan": _entry(
        "research", "post_earnings_drift_scan",
        ["--lock-file", "/tmp/tradingbot_pead_scan.lock",
         "--log-file", f"{BOT_DIR}/pead_scan.log",
         "--timeout-seconds", "10800"],
        ["--", "bash", "-lc",
         _ENV + f'{PY} scripts/pead_label_backfill.py && '
         f'{PY} scripts/post_earnings_drift_research.py '
         "--db-path data/pead_research/pead_research.db scan "
         "--json-output reports/post_earnings_drift/scan_$(date +%F).json"],
    ),

    # ---- Family C — reporting / vault ------------------------------------------------
    "daily_summary": _entry(
        "reporting", "daily_summary",
        ["--lock-file", "/tmp/tradingbot_daily_summary.lock",
         "--log-file", f"{BOT_DIR}/daily_summary.log"],
        ["--", "bash", "-lc", _ENV + f'{PY} scripts/daily_summary.py'],
    ),
    "weekly_summary": _entry(
        "reporting", "weekly_summary",
        ["--lock-file", "/tmp/tradingbot_daily_summary.lock",
         "--log-file", f"{BOT_DIR}/daily_summary.log"],
        ["--", "bash", "-lc", _ENV + f'{PY} scripts/daily_summary.py --week'],
    ),
    "trade_matcher": _entry(
        "reporting", "trade_matcher",
        ["--lock-file", "/tmp/tradingbot_trade_matcher.lock",
         "--log-file", f"{BOT_DIR}/trade_matcher.log"],
        ["--", "bash", "-lc", _ENV + f'{PY} scripts/trade_matcher.py'],
    ),
    "historical_bar_archive": _entry(
        "reporting", "historical_bar_archive_daily",
        ["--lock-file", "/tmp/tradingbot_historical_bar_archive.lock",
         "--log-file", f"{BOT_DIR}/historical_bar_archive.log"],
        ["--", "bash", "-lc",
         _ENV + 'TARGET_DATE=$(date +%F) && '
         f'{PY} pipeline/historical_bar_archive.py --date "$TARGET_DATE" '
         "--all --skip-existing-patterns"],
        date_param=None,  # date server-side $(date +%F)
    ),
}

# Jobs whose family is "learning"/"research" leaf writes are compute/learning DBs, not
# trades.db's writer lock; none of the 11 carry --writer-lock-file in cron (verified against
# the live crontab — the writer-lock jobs are all execution/feature-gen, which are excluded).
# The market-hours guard therefore applies uniformly as a contention-avoidance default.

LEARNING = "learning"
RESEARCH = "research"
REPORTING = "reporting"


# --------------------------------------------------------------------------- validation
def validate_job(job: str) -> dict:
    if job not in ALLOWLIST:
        raise TriggerError(f"unknown job key {job!r} (not in the closed allowlist)")
    return ALLOWLIST[job]


def validate_date(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if not _DATE_RE.match(value):
        raise TriggerError(f"--date {value!r} does not match YYYY-MM-DD")
    try:
        date.fromisoformat(value)
    except ValueError as exc:
        raise TriggerError(f"--date {value!r} is not a real calendar date: {exc}") from exc
    return value


def validate_idempotency_key(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    if not _IDEMPOTENCY_RE.match(value):
        raise TriggerError("--idempotency-key must match ^[A-Za-z0-9_-]{8,64}$")
    return value


# --------------------------------------------------------------------------- argv build
def build_argv(job: str, *, validated_date: Optional[str] = None) -> list[str]:
    """Resolve the FULL argv list for ``job``, with the ``_dt`` provenance suffix and an
    optional validated date appended as a SEPARATE leaf argv element. shell=False ready."""
    entry = validate_job(job)
    job_name = entry["job_name"] + DT_SUFFIX

    argv = [PY, JOB_RUNNER, "--job-name", job_name]
    # Insert the lock/throttle flags VERBATIM (skip the cron --job-name; we set our own).
    argv += list(entry["flags"])
    argv += list(entry["command"])

    # Date is passed as a separate trailing argv element to the leaf python — NEVER spliced
    # into the bash -lc string. Only honored for entries that declare a date_param.
    if validated_date is not None:
        if entry["date_param"] is None:
            raise TriggerError(
                f"job {job!r} does not accept a --date param (date is server-side)")
        argv += [entry["date_param"], validated_date]

    return argv


def deny_scan(argv: list[str]) -> None:
    """Hard-abort if the RESOLVED argv contains any forbidden token (defense-in-depth).

    Scans each argv element individually AND the joined text, so a token split across
    elements or embedded in a bash -lc string is still caught. Whitelisted substrings that
    would false-positive on a benign path are handled by anchoring on the dangerous token
    itself (the 11 safe argv have been verified token-clean by test_dt_trigger.py)."""
    joined = " ".join(argv)
    for token in DENY_TOKENS:
        if token in joined:
            raise TriggerError(
                f"deny-scan: resolved argv contains forbidden token {token!r}; "
                "refusing to dispatch")


# --------------------------------------------------------------------------- guards
def _now() -> datetime:
    return datetime.now()


def market_hours_guard(entry: dict, *, now: Optional[datetime] = None,
                       force: bool = False) -> None:
    """Refuse to trigger during the live trading-loop band (09:00–14:59 Mon–Fri), which is
    when trades.db write contention is highest. ``force`` is the explicit-confirmation
    (L2) escape hatch surfaced by the DT client; default path refuses."""
    if force:
        return
    n = now or _now()
    is_weekday = n.weekday() < 5  # Mon=0 … Fri=4
    in_band = _MARKET_OPEN_HOUR <= n.hour < _MARKET_CLOSE_HOUR
    if is_weekday and in_band:
        raise TriggerError(
            f"market-hours guard: {n:%Y-%m-%d %H:%M} is inside the live trading band "
            f"(09:00–14:59 Mon–Fri); DB-writing safe jobs are deferred to avoid "
            "trades.db contention (pass --force-market-hours only with L2 confirmation)")


def _read_ledger(path: str) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _write_ledger(path: str, data: dict) -> None:
    try:
        with open(path, "w", encoding="utf-8") as fh:
            json.dump(data, fh)
    except OSError:
        # Fail-open on the local throttle ledger: a write failure must not crash the trigger
        # (the DT-side audit ledger is the authoritative tamper-evident record).
        pass


def rate_and_idempotency_guard(family: str, idempotency_key: Optional[str], *,
                               ledger_path: Optional[str] = None,
                               now_ts: Optional[float] = None) -> None:
    """Per-family hourly rate limit + idempotency replay guard (contract §5).

    A duplicate idempotency key within the window is a no-op (raises so the caller treats it
    as already-dispatched). The family cap bounds a compromised-model retry storm.

    ``ledger_path`` defaults to the module-level :data:`_LEDGER_PATH`, resolved at call time
    so tests can monkeypatch the global."""
    if ledger_path is None:
        ledger_path = _LEDGER_PATH
    ts = now_ts if now_ts is not None else time.time()
    ledger = _read_ledger(ledger_path)
    window_start = ts - _IDEMPOTENCY_WINDOW_SEC

    # Idempotency: reject a key seen within the window.
    seen_keys = ledger.get("keys", {})
    if idempotency_key is not None:
        last = seen_keys.get(idempotency_key)
        if last is not None and float(last) >= window_start:
            raise TriggerError(
                f"idempotency-key {idempotency_key!r} already dispatched within the "
                f"{_IDEMPOTENCY_WINDOW_SEC // 60}-min window; no-op")

    # Rate limit: count this family's dispatches in the trailing hour.
    fam_log = [float(t) for t in ledger.get("families", {}).get(family, [])
               if float(t) >= window_start]
    cap = RATE_LIMIT_PER_HOUR.get(family, 4)
    if len(fam_log) >= cap:
        raise TriggerError(
            f"rate limit: family {family!r} already dispatched {len(fam_log)} times in the "
            f"trailing hour (cap {cap})")

    # Record this dispatch.
    fam_log.append(ts)
    ledger.setdefault("families", {})[family] = fam_log
    if idempotency_key is not None:
        ledger.setdefault("keys", {})[idempotency_key] = ts
    _write_ledger(ledger_path, ledger)


# --------------------------------------------------------------------------- dispatch
def dispatch(job: str, *, validated_date: Optional[str], idempotency_key: Optional[str],
             force_market_hours: bool, runner: Callable[..., object],
             now: Optional[datetime] = None) -> dict:
    """Validate → build argv → deny-scan → guards → invoke runner. Pure relative to the
    injected ``runner`` (tests pass a fake; nothing touches WSL/job_runner)."""
    entry = validate_job(job)
    argv = build_argv(job, validated_date=validated_date)
    deny_scan(argv)
    market_hours_guard(entry, now=now, force=force_market_hours)
    rate_and_idempotency_guard(entry["family"], idempotency_key)

    proc = runner(argv, capture_output=True, text=True)
    rc = getattr(proc, "returncode", 1)
    return {
        "job": job,
        "job_name": entry["job_name"] + DT_SUFFIX,
        "dispatched": rc == 0,
        "idempotency_key": idempotency_key,
        "exit_code": rc,
        "stdout": (getattr(proc, "stdout", "") or "").strip()[-2000:],
        "stderr": (getattr(proc, "stderr", "") or "").strip()[-2000:],
    }


def _real_runner(argv, **kwargs):
    # shell=False is the whole point: argv is a list, never a string. We do NOT source
    # /etc/trading-bot.env here — the bot sources it inside its own bash -lc, server-side.
    return subprocess.run(argv, cwd=BOT_DIR, shell=False, **kwargs)  # noqa: S603


# --------------------------------------------------------------------------- CLI
def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="dt_trigger.py",
        description="Deep Thought SAFE-job trigger wrapper (closed allowlist).")
    parser.add_argument("--job", help="one of the closed enum job keys")
    parser.add_argument("--date", default=None, help="optional YYYY-MM-DD (only where accepted)")
    parser.add_argument("--idempotency-key", default=None,
                        help="^[A-Za-z0-9_-]{8,64}$ replay guard")
    parser.add_argument("--force-market-hours", action="store_true",
                        help="L2-confirmation escape hatch to allow the live-band window")
    parser.add_argument("--list", action="store_true", help="print the allowlist and exit")
    args = parser.parse_args(argv)

    if args.list:
        print(json.dumps(
            {k: {"family": v["family"], "job_name": v["job_name"] + DT_SUFFIX}
             for k, v in ALLOWLIST.items()}, indent=2))
        return 0

    try:
        if not args.job:
            raise TriggerError("--job is required unless --list is used")
        validate_job(args.job)
        vdate = validate_date(args.date)
        vkey = validate_idempotency_key(args.idempotency_key)
        result = dispatch(
            args.job, validated_date=vdate, idempotency_key=vkey,
            force_market_hours=args.force_market_hours, runner=_real_runner)
    except TriggerError as exc:
        print(json.dumps({"dispatched": False, "reason": str(exc)}))
        return 2
    print(json.dumps(result))
    return int(result.get("exit_code", 1))


if __name__ == "__main__":
    sys.exit(main())
