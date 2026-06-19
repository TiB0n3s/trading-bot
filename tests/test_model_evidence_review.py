"""Tests for the review orchestrator's cache-read and fail-open behavior.

The review must read the materialized payload cache rather than rebuilding it,
and a missing/stale cache must fail open to a deterministic skeleton WITH a
surfaced warning and a written artifact -- never a silent no-op. The AI passes
are kept disabled (no env opt-in) so these tests make no network calls."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pipeline.model_evidence_review as review
from trading_bot.services.model_evidence_payload_cache_service import (
    DEFAULT_CACHE_MAX_AGE_HOURS,
    health_marker_path,
    write_payload_cache,
)

_DIAG = {"report_version": "model_promotion_evidence_v1", "ready_count": 1, "artifacts": {}}


def _disable_ai(monkeypatch):
    # Force the deterministic (offline) agent regardless of the host's env.
    monkeypatch.delenv("MODEL_EVIDENCE_REVIEW_ENABLED", raising=False)
    monkeypatch.delenv("MODEL_EVIDENCE_PANEL", raising=False)


def _run(tmp_path):
    return review.run("2026-06-18", retrain=False, write=True, emit_vault=False, base_dir=tmp_path)


def test_missing_cache_fails_open_but_still_writes_artifact(monkeypatch, tmp_path):
    _disable_ai(monkeypatch)
    payload = _run(tmp_path)

    assert payload["agent"] == "deterministic_fallback"
    assert payload["cache_status"]["ok"] is False
    assert payload["warnings"]  # surfaced, not silent
    assert payload["review"]["graduated"] is False
    # An artifact lands even on the fail-open path -- the whole point of the fix.
    assert "artifact" in payload
    artifact = json.loads(Path(payload["artifact"]).read_text())
    assert artifact["runtime_effect"]  # observe-only effect carried through


def test_fresh_cache_is_read_not_rebuilt(monkeypatch, tmp_path):
    _disable_ai(monkeypatch)
    write_payload_cache(tmp_path, "2026-06-18", diagnostics=_DIAG, window=("a", "b"))
    payload = _run(tmp_path)

    assert payload["cache_status"]["ok"] is True
    assert payload["cache_status"]["stale"] is False
    assert payload["warnings"] == []
    assert "artifact" in payload


def test_stale_cache_fails_open_with_warning(monkeypatch, tmp_path):
    _disable_ai(monkeypatch)
    old = (
        datetime.now(timezone.utc) - timedelta(hours=DEFAULT_CACHE_MAX_AGE_HOURS + 10)
    ).isoformat()
    write_payload_cache(
        tmp_path, "2026-06-18", diagnostics=_DIAG, window=("a", "b"), generated_at=old
    )
    payload = _run(tmp_path)

    assert payload["agent"] == "deterministic_fallback"
    assert any("stale" in w for w in payload["warnings"])
    assert "artifact" in payload


def test_run_writes_health_marker(monkeypatch, tmp_path):
    _disable_ai(monkeypatch)
    write_payload_cache(tmp_path, "2026-06-18", diagnostics=_DIAG, window=("a", "b"))
    _run(tmp_path)

    marker = health_marker_path(tmp_path)
    assert marker.exists()
    data = json.loads(marker.read_text())
    assert data["target_date"] == "2026-06-18"
    assert data["status"] in {"ok", "graduated_candidate", "degraded_fail_open"}
