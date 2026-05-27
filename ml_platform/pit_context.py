"""Point-in-time context selection for historical replay and dataset export.

Reads from data_archive/point_in_time/ to find the context archive that was
current at a given decision timestamp or date. Prevents historical replay
from reading mutable runtime files (market_context.json, overrides,
strategy_memory.json) whose current state differs from the time of the
original decision.

Archive structure on disk:
  data_archive/point_in_time/{YYYY-MM-DD}/context_state_{YYYYMMDDTHHMMSSZ}.json

Each archive contains:
  archived_at          — ISO timestamp when the archive was created
  archive_reason       — "pre_session" | "post_session" | "manual_archive" | ...
  state_hash           — SHA-256 of {runtime_file_hashes + policy_artifact_hashes}
  symbol_universe_version
  runtime_files        — full JSON content + hashes of market_context.json,
                         manual_strategy_overrides.json, symbol_overrides.json
  policy_artifacts     — hashes of strategy_memory.json and other policy files
  policy_artifacts_full — full JSON content of policy artifacts (added 2026-05-27+)
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any


ARCHIVE_SUBDIR = "point_in_time"
MAX_LOOKBACK_CALENDAR_DAYS = 7


def get_archive_root(base_dir: Path | None = None) -> Path:
    """Return the point-in-time archive root directory."""
    return (
        (base_dir or Path(__file__).resolve().parents[1])
        / "data_archive"
        / ARCHIVE_SUBDIR
    )


@dataclass
class PitContextRecord:
    archive_id: str                  # relative path stem: "2026-05-26/context_state_20260526T205539Z"
    archived_at: str                 # ISO timestamp when archive was created
    archive_reason: str
    state_hash: str
    symbol_universe_version: str | None
    market_context: dict | None      # full market_context.json at archive time
    manual_overrides: dict | None    # full manual_strategy_overrides.json
    symbol_overrides: dict | None    # full symbol_overrides.json
    policy_artifact_hashes: dict     # {filename: sha256 or None}
    strategy_memory: dict | None     # full strategy_memory.json if archive includes it
    has_full_policy_artifacts: bool  # True if policy_artifacts_full present in archive
    coverage_status: str             # "exact" | "best_available" | "prior_date_fallback"
    coverage_note: str

    def to_dict(self) -> dict[str, Any]:
        d = asdict(self)
        # Omit large content blobs from summary dicts to keep manifests compact
        d.pop("market_context", None)
        d.pop("manual_overrides", None)
        d.pop("symbol_overrides", None)
        d.pop("strategy_memory", None)
        return d

    def to_full_dict(self) -> dict[str, Any]:
        return asdict(self)


def _parse_archive_file(path: Path, archive_root: Path) -> PitContextRecord | None:
    try:
        payload = json.loads(path.read_text())
    except Exception:
        return None

    rf = payload.get("runtime_files") or {}
    pa = payload.get("policy_artifacts") or {}
    paf = payload.get("policy_artifacts_full") or {}

    archive_id = str(path.relative_to(archive_root).with_suffix(""))

    return PitContextRecord(
        archive_id=archive_id,
        archived_at=payload.get("archived_at") or "",
        archive_reason=payload.get("archive_reason") or "",
        state_hash=payload.get("state_hash") or "",
        symbol_universe_version=payload.get("symbol_universe_version"),
        market_context=(rf.get("market_context.json") or {}).get("json"),
        manual_overrides=(rf.get("manual_strategy_overrides.json") or {}).get("json"),
        symbol_overrides=(rf.get("symbol_overrides.json") or {}).get("json"),
        policy_artifact_hashes={name: rec.get("sha256") for name, rec in pa.items()},
        strategy_memory=paf.get("strategy_memory.json"),
        has_full_policy_artifacts=bool(paf),
        coverage_status="",
        coverage_note="",
    )


def _list_archives_for_date(date_str: str, archive_root: Path) -> list[Path]:
    date_dir = archive_root / date_str
    if not date_dir.is_dir():
        return []
    return sorted(date_dir.glob("context_state_*.json"))


def select_pit_context(
    decision_timestamp_or_date: str,
    archive_root: Path | None = None,
) -> PitContextRecord | None:
    """Return the best point-in-time context archive for a decision timestamp.

    Selection:
    1. Parse the date from the first 10 chars of the input.
    2. For a full timestamp: take the latest archive in archive_root/{date}/
       whose archived_at <= the decision timestamp.
    3. For a date-only input: take the latest archive for that date.
    4. If no archive exists for that date, look back up to
       MAX_LOOKBACK_CALENDAR_DAYS for the most recent prior archive.
    5. Return None if nothing found within the lookback window.
    """
    if archive_root is None:
        archive_root = get_archive_root()

    date_str = decision_timestamp_or_date[:10]
    is_timestamp = len(decision_timestamp_or_date) > 10

    candidates = _list_archives_for_date(date_str, archive_root)
    for path in reversed(candidates):  # newest first
        record = _parse_archive_file(path, archive_root)
        if record is None:
            continue
        if is_timestamp and record.archived_at > decision_timestamp_or_date:
            continue
        record.coverage_status = "exact"
        record.coverage_note = f"Archive from same date ({date_str})."
        return record

    # Fallback to prior dates
    current = date.fromisoformat(date_str) - timedelta(days=1)
    for _ in range(MAX_LOOKBACK_CALENDAR_DAYS):
        prior_str = current.isoformat()
        prior_candidates = _list_archives_for_date(prior_str, archive_root)
        if prior_candidates:
            record = _parse_archive_file(prior_candidates[-1], archive_root)
            if record is not None:
                record.coverage_status = "prior_date_fallback"
                record.coverage_note = (
                    f"No archive for {date_str}; "
                    f"using prior-date fallback from {prior_str}."
                )
                return record
        current -= timedelta(days=1)

    return None


def pit_coverage_for_range(
    start_date: str,
    end_date: str,
    archive_root: Path | None = None,
) -> dict[str, Any]:
    """Return archive coverage summary for a date range.

    Used by dataset manifest builders to document which point-in-time context
    was in effect for each date in the dataset.
    """
    if archive_root is None:
        archive_root = get_archive_root()

    per_date: dict[str, str | None] = {}
    covered: list[str] = []
    missing: list[str] = []
    fallback: list[str] = []
    no_full_artifacts: list[str] = []

    current = date.fromisoformat(start_date)
    end = date.fromisoformat(end_date)
    while current <= end:
        d = current.isoformat()
        record = select_pit_context(d, archive_root)
        if record is None:
            per_date[d] = None
            missing.append(d)
        else:
            per_date[d] = record.archive_id
            covered.append(d)
            if record.coverage_status == "prior_date_fallback":
                fallback.append(d)
            if not record.has_full_policy_artifacts:
                no_full_artifacts.append(d)
        current += timedelta(days=1)

    total = len(per_date)
    cov_pct = round(len(covered) / total, 3) if total > 0 else 0.0
    if not missing:
        status = "full"
    elif covered:
        status = "partial"
    else:
        status = "none"

    return {
        "start_date": start_date,
        "end_date": end_date,
        "per_date": per_date,
        "covered_dates": covered,
        "missing_dates": missing,
        "fallback_dates": fallback,
        "dates_without_full_policy_artifacts": no_full_artifacts,
        "coverage_pct": cov_pct,
        "status": status,
        "note": (
            "Coverage is 'full' only if every date has a same-date exact archive. "
            "Fallback archives are from prior dates and may not reflect intraday changes. "
            "Dates without full_policy_artifacts cannot restore strategy_memory for replay."
        ),
    }
