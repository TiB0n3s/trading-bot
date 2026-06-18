"""Durable observability for best-effort (fail-open) audit/snapshot writes.

The auto-buy pipeline persists its observation record (candidate snapshots,
blocker counts, episodes) on a *best-effort* basis: under SQLite lock
contention an audit write is dropped with a warning rather than retried
(commit ``8230be2``).  That keeps candidate discovery alive, but it also means
a session's counts can be a *silent* undercount -- a thin count cannot be
distinguished from a lossy capture.

This module makes that loss observable without reintroducing blocking:

* an in-process per-session tally (mirrored into
  :mod:`trading_bot.services.observability` so it shows up on the live metrics
  snapshot / dashboard path), and
* a durable append-only JSONL sidecar that records every dropped write *and* a
  once-per-process session marker.  The sidecar lives outside the contended
  trade database, so a drop caused by lock contention is still recorded even
  when the database itself is unwritable.

Downstream, :func:`reconcile_session` compares rows that actually landed
(counted from the database by the caller) against the durable drop records to
produce an expected-vs-written delta and a ``data_integrity`` classification.

Every write path here is fail-open: instrumentation must never be able to take
down the pipeline it is observing.
"""

from __future__ import annotations

import json
import os
import subprocess
import threading
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

# --- stream identifiers -----------------------------------------------------
# A "stream" is one best-effort audit/snapshot write path.  The value is the
# stable key used both in the sidecar records and in the reconciliation output.
STREAM_AUTO_BUY_SNAPSHOT = "auto_buy_snapshot"
STREAM_CANDIDATE_UNIVERSE = "candidate_universe"
STREAM_INTRADAY_FEEDBACK = "intraday_feedback"
STREAM_BOT_EVENT = "bot_event"

KNOWN_STREAMS = (
    STREAM_AUTO_BUY_SNAPSHOT,
    STREAM_CANDIDATE_UNIVERSE,
    STREAM_INTRADAY_FEEDBACK,
    STREAM_BOT_EVENT,
)

# classifications written into the daily outcome note frontmatter
INTEGRITY_CLEAN = "clean"
INTEGRITY_CONTENDED = "contended"
INTEGRITY_LOSSY = "lossy"
INTEGRITY_INTRASESSION_LOGIC_CHANGE = "intrasession-logic-change"

DEFAULT_REASON = "database_locked"
_SIDECAR_ENV = "AUDIT_WRITE_INTEGRITY_LOG"

_lock = threading.Lock()
# in-process per-session tally: {stream: {"attempts": int, "dropped": int}}
_tally: dict[str, dict[str, int]] = {}
_session_marker_written = False
_cached_git_sha: str | None = None
_git_sha_resolved = False


# --- path resolution --------------------------------------------------------
def default_sidecar_path(base_dir: Path | str | None = None) -> Path:
    """Return the durable sidecar path.

    Resolution order: ``$AUDIT_WRITE_INTEGRITY_LOG`` env override, else
    ``<base_dir>/logs/audit_write_integrity.jsonl``.  ``base_dir`` defaults to
    the repository root inferred from this file's location.
    """
    override = os.getenv(_SIDECAR_ENV)
    if override:
        return Path(override)
    if base_dir is None:
        # src/trading_bot/services/audit_write_integrity.py -> repo root
        base_dir = Path(__file__).resolve().parents[3]
    return Path(base_dir) / "logs" / "audit_write_integrity.jsonl"


# --- git sha ----------------------------------------------------------------
def current_git_sha(base_dir: Path | str | None = None) -> str | None:
    """Return the frozen-logic commit hash (cached for the process).

    Resolving the SHA via ``git`` is done at most once per process so that a
    high-frequency drop loop never spawns a subprocess per dropped write.
    """
    global _cached_git_sha, _git_sha_resolved
    if _git_sha_resolved:
        return _cached_git_sha
    sha = os.getenv("FROZEN_LOGIC_COMMIT") or os.getenv("GIT_SHA")
    if not sha:
        try:
            sha = subprocess.check_output(
                ["git", "rev-parse", "HEAD"],
                cwd=str(base_dir) if base_dir else None,
                text=True,
                stderr=subprocess.DEVNULL,
                timeout=2,
            ).strip()
        except Exception:
            sha = None
    _cached_git_sha = sha or None
    _git_sha_resolved = True
    return _cached_git_sha


def reset_for_tests(*, sidecar_path: Path | str | None = None) -> None:
    """Reset in-process state.  Test-only helper."""
    global _session_marker_written, _cached_git_sha, _git_sha_resolved
    with _lock:
        _tally.clear()
        _session_marker_written = False
        _cached_git_sha = None
        _git_sha_resolved = False
    if sidecar_path is not None:
        try:
            Path(sidecar_path).unlink()
        except FileNotFoundError:
            pass


# --- durable append (fail-open) ---------------------------------------------
def _append_record(record: Mapping[str, Any], sidecar_path: Path | str) -> bool:
    """Append one JSON record to the sidecar.  Never raises."""
    try:
        path = Path(sidecar_path)
        path.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(record, sort_keys=True, default=str)
        with path.open("a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        return True
    except Exception:
        # Instrumentation is best-effort too.  A failure to record a drop must
        # not propagate into the pipeline that is being observed.
        return False


def _ensure_session_marker(
    *,
    sidecar_path: Path | str,
    target_date: str,
    git_sha: str | None,
    now_iso: str,
) -> None:
    """Write a once-per-process marker so a fully clean session still leaves a
    durable record of which frozen-logic commit it ran under."""
    global _session_marker_written
    with _lock:
        if _session_marker_written:
            return
        _session_marker_written = True
    _append_record(
        {
            "kind": "session",
            "ts": now_iso,
            "date": target_date,
            "git_sha": git_sha,
            "pid": os.getpid(),
        },
        sidecar_path,
    )


def record_attempt(
    stream: str,
    *,
    target_date: str | None = None,
    base_dir: Path | str | None = None,
    sidecar_path: Path | str | None = None,
) -> None:
    """Record that a best-effort audit write was attempted.

    Bumps the in-process tally and (once per process) writes a session marker.
    Fail-open: never raises.
    """
    try:
        with _lock:
            bucket = _tally.setdefault(stream, {"attempts": 0, "dropped": 0})
            bucket["attempts"] += 1
        _mirror_to_observability(stream, attempt=True, dropped=False)
        path = sidecar_path or default_sidecar_path(base_dir)
        _ensure_session_marker(
            sidecar_path=path,
            target_date=target_date or _today(),
            git_sha=current_git_sha(base_dir),
            now_iso=_now_iso(),
        )
    except Exception:
        return


def record_drop(
    stream: str,
    *,
    symbol: str | None = None,
    reason: str = DEFAULT_REASON,
    target_date: str | None = None,
    base_dir: Path | str | None = None,
    sidecar_path: Path | str | None = None,
) -> None:
    """Record that a best-effort audit write was dropped (fail-open).

    Bumps the in-process tally, mirrors to the observability snapshot, and
    appends a durable drop record to the sidecar.  Never raises.
    """
    try:
        with _lock:
            bucket = _tally.setdefault(stream, {"attempts": 0, "dropped": 0})
            bucket["dropped"] += 1
        _mirror_to_observability(stream, attempt=False, dropped=True)
        path = sidecar_path or default_sidecar_path(base_dir)
        resolved_date = target_date or _today()
        git_sha = current_git_sha(base_dir)
        _ensure_session_marker(
            sidecar_path=path,
            target_date=resolved_date,
            git_sha=git_sha,
            now_iso=_now_iso(),
        )
        _append_record(
            {
                "kind": "drop",
                "ts": _now_iso(),
                "date": resolved_date,
                "stream": stream,
                "symbol": symbol,
                "reason": reason,
                "git_sha": git_sha,
                "pid": os.getpid(),
            },
            path,
        )
    except Exception:
        return


def _mirror_to_observability(stream: str, *, attempt: bool, dropped: bool) -> None:
    try:
        from services import observability  # scripts/src on path in-process
    except Exception:
        try:
            from trading_bot.services import observability  # package import path
        except Exception:
            return
    record = getattr(observability, "record_audit_write", None)
    if record is not None:
        try:
            record(stream, attempt=attempt, dropped=dropped)
        except Exception:
            return


def session_tally() -> dict[str, dict[str, int]]:
    """Return a copy of the in-process per-session tally."""
    with _lock:
        return {stream: dict(counts) for stream, counts in _tally.items()}


def session_dropped_total() -> int:
    with _lock:
        return sum(counts.get("dropped", 0) for counts in _tally.values())


# --- reconciliation ---------------------------------------------------------
def read_records(target_date: str, *, sidecar_path: Path | str) -> list[dict[str, Any]]:
    """Read sidecar records for ``target_date``.  Tolerant of partial lines."""
    path = Path(sidecar_path)
    if not path.exists():
        return []
    records: list[dict[str, Any]] = []
    try:
        with path.open("r", encoding="utf-8", errors="replace") as fh:
            for raw in fh:
                line = raw.strip()
                if not line:
                    continue
                try:
                    record = json.loads(line)
                except Exception:
                    continue
                if record.get("date") == target_date:
                    records.append(record)
    except OSError:
        return records
    return records


def summarize_records(target_date: str, *, sidecar_path: Path | str) -> dict[str, Any]:
    records = read_records(target_date, sidecar_path=sidecar_path)
    drops = [r for r in records if r.get("kind") == "drop"]
    by_stream: Counter[str] = Counter(str(r.get("stream") or "unknown") for r in drops)
    git_shas = sorted(
        {str(r.get("git_sha")) for r in records if r.get("git_sha")}
    )
    return {
        "dropped_total": len(drops),
        "dropped_by_stream": dict(by_stream),
        "session_git_shas": git_shas,
        "session_runs": sum(1 for r in records if r.get("kind") == "session"),
    }


def classify_session(
    *,
    dropped_total: int,
    contended: bool,
    distinct_git_shas: Iterable[str],
) -> str:
    """Classify a session's observation record.

    Precedence (most-to-least disqualifying for count comparability):
    intrasession-logic-change > lossy > contended > clean.
    """
    shas = {s for s in distinct_git_shas if s}
    if len(shas) > 1:
        return INTEGRITY_INTRASESSION_LOGIC_CHANGE
    if dropped_total > 0:
        return INTEGRITY_LOSSY
    if contended:
        return INTEGRITY_CONTENDED
    return INTEGRITY_CLEAN


def reconcile_session(
    target_date: str,
    *,
    written_counts: Mapping[str, int],
    sidecar_path: Path | str,
    contended: bool = False,
    frozen_logic_commit: str | None = None,
    writer_overlap: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    """Reconcile rows that landed against durably-recorded dropped writes.

    ``written_counts`` maps stream -> rows that actually landed in the database
    (counted by the caller).  Returns a reconciliation dict including the
    expected-vs-written delta per stream and a ``data_integrity`` classification
    plus a frontmatter-ready block for the daily outcome note.
    """
    summary = summarize_records(target_date, sidecar_path=sidecar_path)
    dropped_by_stream = summary["dropped_by_stream"]
    dropped_total = summary["dropped_total"]
    git_shas = summary["session_git_shas"]

    streams = sorted(set(written_counts) | set(dropped_by_stream) | set(KNOWN_STREAMS))
    written: dict[str, int] = {}
    dropped: dict[str, int] = {}
    expected: dict[str, int] = {}
    delta: dict[str, int] = {}
    for stream in streams:
        w = int(written_counts.get(stream, 0) or 0)
        d = int(dropped_by_stream.get(stream, 0) or 0)
        written[stream] = w
        dropped[stream] = d
        expected[stream] = w + d
        delta[stream] = d
    written_total = sum(written.values())

    classification = classify_session(
        dropped_total=dropped_total,
        contended=contended,
        distinct_git_shas=git_shas,
    )

    # Prefer an explicitly-frozen commit; otherwise fall back to the SHA the
    # session actually recorded (single value when logic was stable).
    if frozen_logic_commit is None and len(git_shas) == 1:
        frozen_logic_commit = git_shas[0]

    dropped_known = summary["session_runs"] > 0 or dropped_total > 0
    dropped_field: int | str = dropped_total if dropped_known else "unknown"

    return {
        "target_date": target_date,
        "data_integrity": classification,
        "frozen_logic_commit": frozen_logic_commit,
        "session_git_shas": git_shas,
        "session_runs": summary["session_runs"],
        "contended": bool(contended),
        "writer_overlap": dict(writer_overlap) if writer_overlap else None,
        "written": {**written, "total": written_total},
        "dropped": {**dropped, "total": dropped_total},
        "expected": {**expected, "total": written_total + dropped_total},
        "delta": {**delta, "total": dropped_total},
        "dropped_known": dropped_known,
        "frontmatter": {
            "data_integrity": classification,
            "dropped_audit_writes": dropped_field,
            "frozen_logic_commit": frozen_logic_commit,
        },
    }


# --- small helpers ----------------------------------------------------------
def _now_iso() -> str:
    try:
        from market_time import now_et  # scripts on path in-process

        return now_et().isoformat()
    except Exception:
        return datetime.now().astimezone().isoformat()


def _today() -> str:
    return _now_iso()[:10]
