"""Operator check: per-session audit/snapshot write reconciliation.

Best-effort audit writes are fail-open under SQLite lock contention, so a
session's observation counts (candidate snapshots, blocker counts, episodes)
can be a *silent* undercount.  This check reconciles rows that actually landed
in the database against the durable drop records left by
:mod:`trading_bot.services.audit_write_integrity`, and classifies the session's
``data_integrity`` so a thin count is distinguishable from a lossy one.

Read-only: it never writes to the trade database.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

from repositories.audit_write_integrity_repo import (
    WRITTEN_COUNT_SOURCES,
    written_counts_for_date,
)

from services import audit_write_integrity


def _writer_overlap(db_path: Path, target_date: str) -> tuple[bool, dict[str, Any] | None]:
    """Return (contended, overlap_summary) using the existing workload report."""
    try:
        from db_workload_report import _writer_overlap_report
    except Exception:
        return False, None
    try:
        overlap = _writer_overlap_report(
            db_path,
            target_date=target_date,
            auto_buy_job_name="auto_buy_manager",
            watch_writer_jobs=("run_label_features", "session_momentum"),
            duration_threshold_sec=60.0,
            limit=5,
        )
    except Exception:
        return False, None
    contended = int(overlap.get("long_running_overlap_count") or 0) > 0
    summary = {
        "auto_buy_runs": overlap.get("auto_buy_runs"),
        "watched_runs": overlap.get("watched_runs"),
        "overlap_count": overlap.get("overlap_count"),
        "long_running_overlap_count": overlap.get("long_running_overlap_count"),
        "warning": overlap.get("warning"),
    }
    return contended, summary


def run_audit_write_integrity(target_date: str, *, base_dir: Path) -> bool:
    db_path = base_dir / "trades.db"
    sidecar_path = audit_write_integrity.default_sidecar_path(base_dir)

    print()
    print("=" * 72)
    print(f"  Audit-Write Integrity - {target_date}")
    print("=" * 72)
    print("runtime_effect=diagnostic_only_read_only")
    print(f"  db_path        : {db_path}")
    print(f"  sidecar        : {sidecar_path}")

    if not db_path.exists():
        print(f"[FAIL] missing {db_path}")
        return False

    written = written_counts_for_date(target_date, db_path)
    contended, overlap_summary = _writer_overlap(db_path, target_date)

    reconciliation = audit_write_integrity.reconcile_session(
        target_date,
        written_counts=written,
        sidecar_path=sidecar_path,
        contended=contended,
        writer_overlap=overlap_summary,
    )

    print()
    print("Per-stream reconciliation (expected = written + dropped)")
    print(f"  {'stream':<22}{'written':>10}{'dropped':>10}{'expected':>10}")
    for stream in sorted(WRITTEN_COUNT_SOURCES):
        w = reconciliation["written"].get(stream, 0)
        d = reconciliation["dropped"].get(stream, 0)
        e = reconciliation["expected"].get(stream, 0)
        print(f"  {stream:<22}{w:>10}{d:>10}{e:>10}")
    print(f"  {'TOTAL':<22}"
          f"{reconciliation['written']['total']:>10}"
          f"{reconciliation['dropped']['total']:>10}"
          f"{reconciliation['expected']['total']:>10}")

    if overlap_summary is not None:
        print()
        print("Writer overlap (jobs ledger)")
        print(f"  auto_buy_runs              : {overlap_summary.get('auto_buy_runs')}")
        print(f"  long_running_overlap_count : {overlap_summary.get('long_running_overlap_count')}")
        if overlap_summary.get("warning"):
            print(f"  warning                    : {overlap_summary.get('warning')}")

    dropped_total = reconciliation["dropped"]["total"]
    classification = reconciliation["data_integrity"]
    print()
    print("Classification")
    print(f"  data_integrity     : {classification}")
    print(f"  dropped_audit_writes: {reconciliation['frontmatter']['dropped_audit_writes']}")
    print(f"  frozen_logic_commit: {reconciliation['frozen_logic_commit'] or 'unknown'}")
    print(f"  session_git_shas   : {', '.join(reconciliation['session_git_shas']) or 'none'}")

    print()
    print("Daily-outcome frontmatter block")
    print(f"data_integrity: {classification}")
    fm_dropped = reconciliation["frontmatter"]["dropped_audit_writes"]
    print(f"dropped_audit_writes: {fm_dropped}")
    print(f"frozen_logic_commit: {reconciliation['frozen_logic_commit'] or 'unknown'}")

    print()
    if classification == audit_write_integrity.INTEGRITY_LOSSY:
        print(f"[WARN] session is LOSSY: {dropped_total} audit/snapshot write(s) were dropped")
        # Loss is a reportable data-integrity finding, but the pipeline itself
        # stayed up by design; surface it without failing the operator wrapper.
        return True
    if classification == audit_write_integrity.INTEGRITY_INTRASESSION_LOGIC_CHANGE:
        print("[WARN] frozen logic changed mid-session; counts are not directly comparable")
        return True
    if classification == audit_write_integrity.INTEGRITY_CONTENDED:
        print("[OK] contended but no recorded audit-write loss")
        return True
    print("[OK] clean: no recorded audit-write loss")
    return True
