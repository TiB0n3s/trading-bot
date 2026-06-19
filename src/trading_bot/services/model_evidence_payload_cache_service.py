"""Materialized cache for the heavy model-promotion evidence payload.

The model-evidence review used to rebuild the ~2-year diagnostics payload inside
its own scheduled slot. Under ``ionice-idle``/``nice`` and competing dark-hours
I/O that build could not finish before the job_runner timeout (observed >1h45m
wall on ~5min CPU, killed by SIGTERM), so the review never reached its LLM
passes or wrote an artifact -- silently.

This module decouples the two: a separate, generously-timed build job
(``pipeline/model_evidence_payload_export.py``) materializes the diagnostics
payload here as a cached export, mirroring the columnar ``research_exports/``
pattern, and the fast review job reads it instead of rebuilding it.

Observe-only: the cached payload carries no live authority. It is read-only with
respect to ``trades.db``, broker state, orders, sizing, and risk controls -- it
only persists numeric diagnostics already produced by
``model_promotion_evidence_service``. This module is intentionally stdlib-only so
the review's fail-open path never pulls a heavy import to decide a cache miss.
"""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

CACHE_VERSION = "model_evidence_payload_cache_v1"
# Same observe-only lane as the research exports this mirrors.
CACHE_RUNTIME_EFFECT = "offline_research_only_no_live_authority"

# Cache lives beside the columnar research exports it is modelled on.
CACHE_SUBDIR = ("research_exports", "model_evidence_payload")

# How old a cached payload may be before the review treats it as stale and fails
# open. The build runs the same dark hours as the review (Tue-Sat), so a healthy
# nightly build is <2h old by review time; 30h catches a skipped/failed build
# while tolerating a same-night build plus slack.
DEFAULT_CACHE_MAX_AGE_HOURS = 30.0

# Review schedule, as Python weekdays (Mon=0 .. Sun=6): Tue-Sat. Used by the
# health check so a legitimately-absent Monday artifact is not flagged.
DEFAULT_REVIEW_WEEKDAYS = (1, 2, 3, 4, 5)

# Mirrors run_model_evidence_review.py's artifact location so the health check
# can confirm an artifact actually landed for the expected review date.
AI_REVIEW_SUBDIR = ("ops", "model_promotion_evidence", "ai_review")

# Where the review records its last-run outcome so a human (via daily_summary)
# can see a degraded/fail-open run even when an artifact was still written.
HEALTH_MARKER_SUBDIR = ("runtime_state", "pipeline_health")
HEALTH_MARKER_NAME = "model_evidence_review.json"


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def historical_window(date: str) -> tuple[str, str]:
    """Recent window for the historical-bar validation inside the payload build.

    The full 2-year default in the service is impractical against the 23.6 GB
    live DB. The validation query is ``ORDER BY bar_timestamp ASC LIMIT n`` per
    symbol, so it reads from the OLDEST date forward; old bars are sparse on the
    current ``feature_version``/labels, so a wide window scans months to collect
    each symbol's sample (measured: 90d ~= 168s per call, ~11min for the build;
    14d ~= 0.1s). A short recent window keeps the build in its slot at the cost
    of shallower (fewer-than-5000-row) coverage — honestly reported as not-ready,
    never inflated. Raise MODEL_EVIDENCE_HISTORICAL_DAYS to widen coverage once
    the validation is sourced from columnar exports instead of the live DB.
    """
    try:
        days = int(os.environ.get("MODEL_EVIDENCE_HISTORICAL_DAYS", "14"))
    except ValueError:
        days = 14
    try:
        end = datetime.strptime(date, "%Y-%m-%d").date()
    except ValueError:
        end = _utc_now().date()
    return (end - timedelta(days=days)).isoformat(), end.isoformat()


def cache_dir(base_dir: Path) -> Path:
    return Path(base_dir).joinpath(*CACHE_SUBDIR)


def cache_path(base_dir: Path, date: str) -> Path:
    return cache_dir(base_dir) / f"{date}.json"


def write_payload_cache(
    base_dir: Path,
    date: str,
    *,
    diagnostics: dict[str, Any],
    window: tuple[str, str],
    build_duration_seconds: float | None = None,
    generated_at: str | None = None,
) -> Path:
    """Persist the diagnostics payload as a cached export and return its path."""
    out_dir = cache_dir(base_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    wrapper = {
        "cache_version": CACHE_VERSION,
        "runtime_effect": CACHE_RUNTIME_EFFECT,
        "target_date": date,
        "window": list(window),
        "generated_at": generated_at or _utc_now().isoformat(),
        "build_duration_seconds": build_duration_seconds,
        "diagnostics": diagnostics,
    }
    out_path = cache_path(base_dir, date)
    out_path.write_text(json.dumps(wrapper, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return out_path


@dataclass(frozen=True)
class PayloadCacheRead:
    ok: bool
    reason: str
    diagnostics: dict[str, Any] | None = None
    path: str | None = None
    target_date: str | None = None
    generated_at: str | None = None
    age_hours: float | None = None
    stale: bool = False
    window: list[str] = field(default_factory=list)

    def summary(self) -> dict[str, Any]:
        """Compact, JSON-safe state for embedding in the review artifact."""
        return {
            "ok": self.ok,
            "reason": self.reason,
            "path": self.path,
            "target_date": self.target_date,
            "generated_at": self.generated_at,
            "age_hours": round(self.age_hours, 2) if self.age_hours is not None else None,
            "stale": self.stale,
            "window": self.window,
        }


def _parse_generated_at(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _select_cache_file(base_dir: Path, date: str) -> Path | None:
    """Prefer the exact date; else the most recent on-or-before it.

    ISO date stems sort lexicographically, so the newest eligible file is the
    max stem <= ``date``.
    """
    exact = cache_path(base_dir, date)
    if exact.exists():
        return exact
    directory = cache_dir(base_dir)
    if not directory.exists():
        return None
    candidates = sorted(
        (p for p in directory.glob("*.json") if p.stem <= date),
        key=lambda p: p.stem,
    )
    return candidates[-1] if candidates else None


def read_payload_cache(
    base_dir: Path,
    *,
    date: str,
    max_age_hours: float = DEFAULT_CACHE_MAX_AGE_HOURS,
    now: datetime | None = None,
) -> PayloadCacheRead:
    """Read the freshest cached payload at-or-before ``date``.

    Returns a structured result the caller can act on; never raises on a missing
    or malformed cache so the review's fail-open path stays simple.
    """
    now = now or _utc_now()
    selected = _select_cache_file(base_dir, date)
    if selected is None:
        return PayloadCacheRead(ok=False, reason="cache_missing")
    try:
        wrapper = json.loads(selected.read_text(encoding="utf-8"))
    except Exception as exc:  # corrupt/partial write -> treat as missing
        return PayloadCacheRead(
            ok=False, reason=f"cache_unreadable: {str(exc)[:120]}", path=str(selected)
        )
    if not isinstance(wrapper, dict):
        return PayloadCacheRead(ok=False, reason="cache_malformed", path=str(selected))
    diagnostics = wrapper.get("diagnostics")
    if not isinstance(diagnostics, dict):
        return PayloadCacheRead(ok=False, reason="cache_missing_diagnostics", path=str(selected))

    generated_at = wrapper.get("generated_at")
    parsed = _parse_generated_at(generated_at)
    age_hours = (now - parsed).total_seconds() / 3600.0 if parsed else None
    # An unparseable timestamp is treated as stale rather than silently fresh.
    stale = age_hours is None or age_hours > max_age_hours
    window = wrapper.get("window") if isinstance(wrapper.get("window"), list) else []
    return PayloadCacheRead(
        ok=True,
        reason="stale" if stale else "fresh",
        diagnostics=diagnostics,
        path=str(selected),
        target_date=str(wrapper.get("target_date") or selected.stem),
        generated_at=generated_at if isinstance(generated_at, str) else None,
        age_hours=age_hours,
        stale=stale,
        window=[str(w) for w in window],
    )


def _most_recent_review_date(as_of: datetime, review_weekdays: tuple[int, ...]) -> str | None:
    """Most recent date on-or-before ``as_of`` on which a review was scheduled."""
    if not review_weekdays:
        return None
    day = as_of.date()
    for _ in range(8):
        if day.weekday() in review_weekdays:
            return day.isoformat()
        day = day - timedelta(days=1)
    return None


def _newest_artifact(base_dir: Path, date: str) -> Path | None:
    directory = Path(base_dir).joinpath(*AI_REVIEW_SUBDIR)
    if not directory.exists():
        return None
    matches = sorted(directory.glob(f"{date}_*.json"))
    return matches[-1] if matches else None


def health_marker_path(base_dir: Path) -> Path:
    return Path(base_dir).joinpath(*HEALTH_MARKER_SUBDIR, HEALTH_MARKER_NAME)


def write_health_marker(base_dir: Path, marker: dict[str, Any]) -> Path:
    path = health_marker_path(base_dir)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {"runtime_effect": CACHE_RUNTIME_EFFECT, **marker}
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return path


def _read_health_marker(base_dir: Path) -> dict[str, Any] | None:
    path = health_marker_path(base_dir)
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None
    return data if isinstance(data, dict) else None


def model_evidence_review_health(
    base_dir: Path,
    *,
    as_of_date: str | None = None,
    review_weekdays: tuple[int, ...] = DEFAULT_REVIEW_WEEKDAYS,
    cache_max_age_hours: float = DEFAULT_CACHE_MAX_AGE_HOURS,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Surface whether the observe-only model-evidence review is healthy.

    A scheduled run that produces no artifact must not be invisible, so this
    independently checks (a) that an AI-review artifact exists for the most
    recent *expected* review date and (b) that the materialized payload cache is
    fresh. It reads the review's last-run health marker too, but does not depend
    on it -- if the review process was killed before writing the marker, the
    missing-artifact check still fires. Observe-only and read-only.
    """
    now = now or _utc_now()
    if as_of_date:
        try:
            as_of = datetime.strptime(as_of_date, "%Y-%m-%d").replace(tzinfo=timezone.utc)
        except ValueError:
            as_of = now
    else:
        as_of = now

    expected_date = _most_recent_review_date(as_of, tuple(review_weekdays))
    artifact = _newest_artifact(base_dir, expected_date) if expected_date else None
    cache = read_payload_cache(
        base_dir, date=as_of.date().isoformat(), max_age_hours=cache_max_age_hours, now=now
    )
    marker = _read_health_marker(base_dir)

    warnings: list[str] = []
    if expected_date and artifact is None:
        warnings.append(
            f"no model-evidence AI review artifact for expected review date {expected_date}"
        )
    if not cache.ok:
        warnings.append(f"model-evidence payload cache unavailable ({cache.reason})")
    elif cache.stale:
        age = f"{cache.age_hours:.1f}h" if cache.age_hours is not None else "unknown age"
        warnings.append(f"model-evidence payload cache is stale ({age})")
    if marker and marker.get("status") not in (None, "ok", "graduated_candidate"):
        reason = str(marker.get("status"))
        warnings.append(f"last model-evidence review run was degraded ({reason})")

    return {
        "runtime_effect": CACHE_RUNTIME_EFFECT,
        "ok": not warnings,
        "expected_review_date": expected_date,
        "artifact_present": artifact is not None,
        "artifact_path": str(artifact) if artifact else None,
        "cache": cache.summary(),
        "last_run_marker": marker,
        "warnings": warnings,
    }
