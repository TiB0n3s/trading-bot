#!/usr/bin/env python3
"""Tests for the audit-write integrity service (durable fail-open accounting)."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
for path in (str(ROOT), str(ROOT / "scripts"), str(ROOT / "src")):
    if path not in sys.path:
        sys.path.insert(0, path)

from services import audit_write_integrity as awi  # noqa: E402
from services import observability  # noqa: E402


def _write_sidecar(path: Path, records: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for record in records:
            fh.write(json.dumps(record) + "\n")


def test_record_drop_is_durable_and_tallies(tmp_path):
    sidecar = tmp_path / "logs" / "audit.jsonl"
    awi.reset_for_tests(sidecar_path=sidecar)
    observability.reset_metrics()

    awi.record_attempt(awi.STREAM_AUTO_BUY_SNAPSHOT, target_date="2026-06-18", sidecar_path=sidecar)
    awi.record_drop(
        awi.STREAM_AUTO_BUY_SNAPSHOT,
        symbol="TSM",
        target_date="2026-06-18",
        sidecar_path=sidecar,
    )

    # in-process tally
    tally = awi.session_tally()
    assert tally[awi.STREAM_AUTO_BUY_SNAPSHOT]["attempts"] == 1
    assert tally[awi.STREAM_AUTO_BUY_SNAPSHOT]["dropped"] == 1
    assert awi.session_dropped_total() == 1

    # durable record
    records = awi.read_records("2026-06-18", sidecar_path=sidecar)
    drops = [r for r in records if r.get("kind") == "drop"]
    assert len(drops) == 1
    assert drops[0]["symbol"] == "TSM"
    assert any(r.get("kind") == "session" for r in records)

    # mirrored to observability snapshot
    snapshot = observability.metrics_snapshot()
    bucket = snapshot["audit_write_failopen"][awi.STREAM_AUTO_BUY_SNAPSHOT]
    assert bucket["dropped"] == 1
    assert bucket["drop_rate"] == 1.0


def test_record_drop_never_raises_when_sidecar_unwritable(tmp_path, monkeypatch):
    awi.reset_for_tests()

    def _boom(*_args, **_kwargs):
        raise OSError("disk gone")

    monkeypatch.setattr(awi, "_append_record", _boom)
    # Must not raise even though the durable append fails.
    awi.record_drop(awi.STREAM_BOT_EVENT, symbol="AAPL", target_date="2026-06-18",
                    sidecar_path=tmp_path / "x.jsonl")
    assert awi.session_dropped_total() == 1


def test_classify_session_all_states():
    assert awi.classify_session(dropped_total=0, contended=False, distinct_git_shas=["a"]) == (
        awi.INTEGRITY_CLEAN
    )
    assert awi.classify_session(dropped_total=0, contended=True, distinct_git_shas=["a"]) == (
        awi.INTEGRITY_CONTENDED
    )
    assert awi.classify_session(dropped_total=5, contended=True, distinct_git_shas=["a"]) == (
        awi.INTEGRITY_LOSSY
    )
    # logic change dominates even when drops/contention are present
    assert awi.classify_session(
        dropped_total=5, contended=True, distinct_git_shas=["a", "b"]
    ) == awi.INTEGRITY_INTRASESSION_LOGIC_CHANGE


def test_reconcile_lossy_with_expected_delta(tmp_path):
    sidecar = tmp_path / "audit.jsonl"
    _write_sidecar(
        sidecar,
        [
            {"kind": "session", "date": "2026-06-18", "git_sha": "sha1"},
            {"kind": "drop", "date": "2026-06-18", "stream": awi.STREAM_AUTO_BUY_SNAPSHOT,
             "git_sha": "sha1"},
            {"kind": "drop", "date": "2026-06-18", "stream": awi.STREAM_AUTO_BUY_SNAPSHOT,
             "git_sha": "sha1"},
            {"kind": "drop", "date": "2026-06-18", "stream": awi.STREAM_CANDIDATE_UNIVERSE,
             "git_sha": "sha1"},
            {"kind": "drop", "date": "2026-06-17", "stream": awi.STREAM_AUTO_BUY_SNAPSHOT,
             "git_sha": "sha1"},  # different date, ignored
        ],
    )

    result = awi.reconcile_session(
        "2026-06-18",
        written_counts={awi.STREAM_AUTO_BUY_SNAPSHOT: 100, awi.STREAM_CANDIDATE_UNIVERSE: 50},
        sidecar_path=sidecar,
        contended=True,
    )

    assert result["data_integrity"] == awi.INTEGRITY_LOSSY
    assert result["dropped"][awi.STREAM_AUTO_BUY_SNAPSHOT] == 2
    assert result["dropped"]["total"] == 3
    assert result["written"]["total"] == 150
    assert result["expected"][awi.STREAM_AUTO_BUY_SNAPSHOT] == 102
    assert result["expected"]["total"] == 153
    assert result["delta"]["total"] == 3
    # single recorded sha becomes the frozen-logic commit
    assert result["frozen_logic_commit"] == "sha1"
    assert result["frontmatter"]["dropped_audit_writes"] == 3
    assert result["frontmatter"]["data_integrity"] == awi.INTEGRITY_LOSSY


def test_reconcile_clean_session_reports_zero_not_unknown(tmp_path):
    sidecar = tmp_path / "audit.jsonl"
    _write_sidecar(
        sidecar,
        [{"kind": "session", "date": "2026-06-18", "git_sha": "shaX"}],
    )
    result = awi.reconcile_session(
        "2026-06-18",
        written_counts={awi.STREAM_AUTO_BUY_SNAPSHOT: 10},
        sidecar_path=sidecar,
        contended=False,
    )
    assert result["data_integrity"] == awi.INTEGRITY_CLEAN
    assert result["dropped_known"] is True
    assert result["frontmatter"]["dropped_audit_writes"] == 0


def test_reconcile_unknown_when_no_instrumentation(tmp_path):
    sidecar = tmp_path / "missing.jsonl"  # never created
    result = awi.reconcile_session(
        "2026-06-17",
        written_counts={awi.STREAM_AUTO_BUY_SNAPSHOT: 5869},
        sidecar_path=sidecar,
        contended=True,
    )
    # contention but no durable records -> contended, dropped unknown
    assert result["data_integrity"] == awi.INTEGRITY_CONTENDED
    assert result["dropped_known"] is False
    assert result["frontmatter"]["dropped_audit_writes"] == "unknown"


def test_reconcile_intrasession_logic_change(tmp_path):
    sidecar = tmp_path / "audit.jsonl"
    _write_sidecar(
        sidecar,
        [
            {"kind": "session", "date": "2026-06-18", "git_sha": "sha_before"},
            {"kind": "session", "date": "2026-06-18", "git_sha": "sha_after"},
        ],
    )
    result = awi.reconcile_session(
        "2026-06-18",
        written_counts={awi.STREAM_AUTO_BUY_SNAPSHOT: 10},
        sidecar_path=sidecar,
        contended=False,
    )
    assert result["data_integrity"] == awi.INTEGRITY_INTRASESSION_LOGIC_CHANGE
    assert sorted(result["session_git_shas"]) == ["sha_after", "sha_before"]


def main():
    import tempfile

    tests = [
        test_classify_session_all_states,
    ]
    # The tmp_path-based tests are exercised under pytest; provide a minimal
    # runner for the no-fixture test so `python3 tests/...` still works.
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")
    with tempfile.TemporaryDirectory() as tmp:
        tmp_path = Path(tmp)
        for test in (
            test_reconcile_lossy_with_expected_delta,
            test_reconcile_clean_session_reports_zero_not_unknown,
            test_reconcile_unknown_when_no_instrumentation,
            test_reconcile_intrasession_logic_change,
        ):
            test(tmp_path)
            print(f"[OK] {test.__name__}")
    print("\nAll audit-write integrity service tests passed.")


if __name__ == "__main__":
    main()
