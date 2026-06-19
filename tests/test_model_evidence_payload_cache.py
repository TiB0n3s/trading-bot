"""Tests for the materialized model-evidence payload cache and its health check.

Covers the cache-read path (round-trip, freshest-on-or-before selection),
staleness/missing fail-open signals, and the observe-only health surfacing that
keeps a no-artifact run from being invisible. Pure filesystem + stdlib, no
network and no live DB."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from trading_bot.services.model_evidence_payload_cache_service import (
    AI_REVIEW_SUBDIR,
    CACHE_RUNTIME_EFFECT,
    DEFAULT_CACHE_MAX_AGE_HOURS,
    model_evidence_review_health,
    read_payload_cache,
    write_health_marker,
    write_payload_cache,
)

_DIAG = {"report_version": "model_promotion_evidence_v1", "ready_count": 3, "artifacts": {}}


def test_write_then_read_roundtrip_is_fresh(tmp_path):
    path = write_payload_cache(
        tmp_path, "2026-06-18", diagnostics=_DIAG, window=("2026-03-20", "2026-06-18")
    )
    assert path.exists()
    wrapper = json.loads(path.read_text())
    assert wrapper["runtime_effect"] == CACHE_RUNTIME_EFFECT  # observe-only preserved

    result = read_payload_cache(tmp_path, date="2026-06-18")
    assert result.ok is True
    assert result.stale is False
    assert result.diagnostics == _DIAG
    assert result.window == ["2026-03-20", "2026-06-18"]


def test_missing_cache_fails_open(tmp_path):
    result = read_payload_cache(tmp_path, date="2026-06-18")
    assert result.ok is False
    assert result.reason == "cache_missing"
    assert result.diagnostics is None


def test_stale_cache_is_flagged(tmp_path):
    old = (
        datetime.now(timezone.utc) - timedelta(hours=DEFAULT_CACHE_MAX_AGE_HOURS + 5)
    ).isoformat()
    write_payload_cache(
        tmp_path,
        "2026-06-18",
        diagnostics=_DIAG,
        window=("2026-03-20", "2026-06-18"),
        generated_at=old,
    )
    result = read_payload_cache(tmp_path, date="2026-06-18")
    assert result.ok is True  # readable...
    assert result.stale is True  # ...but flagged so the review can fail open loudly
    assert result.age_hours > DEFAULT_CACHE_MAX_AGE_HOURS


def test_reads_freshest_on_or_before_date(tmp_path):
    write_payload_cache(tmp_path, "2026-06-16", diagnostics={"d": 16}, window=("a", "b"))
    write_payload_cache(tmp_path, "2026-06-17", diagnostics={"d": 17}, window=("a", "b"))
    # No exact 2026-06-18 file -> fall back to the most recent prior cache.
    result = read_payload_cache(tmp_path, date="2026-06-18")
    assert result.ok is True
    assert result.diagnostics == {"d": 17}
    assert result.target_date == "2026-06-17"


def test_corrupt_cache_is_treated_as_missing(tmp_path):
    bad = tmp_path / "research_exports" / "model_evidence_payload" / "2026-06-18.json"
    bad.parent.mkdir(parents=True, exist_ok=True)
    bad.write_text("{ not json")
    result = read_payload_cache(tmp_path, date="2026-06-18")
    assert result.ok is False
    assert "unreadable" in result.reason


def _write_artifact(base, date: str) -> None:
    d = base.joinpath(*AI_REVIEW_SUBDIR)
    d.mkdir(parents=True, exist_ok=True)
    (d / f"{date}_20260618T000000Z.json").write_text("{}")


def test_health_ok_when_artifact_and_fresh_cache_present(tmp_path):
    # 2026-06-18 is a Thursday -> a review was expected for it.
    write_payload_cache(tmp_path, "2026-06-18", diagnostics=_DIAG, window=("a", "b"))
    _write_artifact(tmp_path, "2026-06-18")
    health = model_evidence_review_health(tmp_path, as_of_date="2026-06-18")
    assert health["ok"] is True
    assert health["artifact_present"] is True
    assert health["warnings"] == []


def test_health_warns_on_missing_artifact_for_expected_day(tmp_path):
    write_payload_cache(tmp_path, "2026-06-18", diagnostics=_DIAG, window=("a", "b"))
    # No artifact written -> the expected Thursday review left nothing behind.
    health = model_evidence_review_health(tmp_path, as_of_date="2026-06-18")
    assert health["ok"] is False
    assert health["artifact_present"] is False
    assert any("no model-evidence AI review artifact" in w for w in health["warnings"])


def test_health_does_not_warn_on_monday_when_no_review_expected(tmp_path):
    # 2026-06-15 is a Monday; the review schedule is Tue-Sat, so the most recent
    # expected review date is the prior Saturday 2026-06-13.
    write_payload_cache(tmp_path, "2026-06-15", diagnostics=_DIAG, window=("a", "b"))
    _write_artifact(tmp_path, "2026-06-13")
    health = model_evidence_review_health(tmp_path, as_of_date="2026-06-15")
    assert health["expected_review_date"] == "2026-06-13"
    assert health["ok"] is True


def test_health_includes_degraded_marker(tmp_path):
    write_payload_cache(tmp_path, "2026-06-18", diagnostics=_DIAG, window=("a", "b"))
    _write_artifact(tmp_path, "2026-06-18")
    write_health_marker(tmp_path, {"status": "degraded_fail_open", "warnings": ["x"]})
    health = model_evidence_review_health(tmp_path, as_of_date="2026-06-18")
    assert health["ok"] is False
    assert any("degraded" in w for w in health["warnings"])
