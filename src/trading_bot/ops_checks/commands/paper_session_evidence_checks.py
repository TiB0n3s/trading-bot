"""Paper-session evidence report for ML/intelligence authority review."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from services.paper_session_evidence_service import build_paper_session_evidence_payload


def _fmt(value: Any) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def _pct(value: Any) -> str:
    if value is None:
        return "-"
    try:
        return f"{float(value) * 100:.2f}%"
    except Exception:
        return str(value)


def run_paper_session_evidence(target_date: str, *, base_dir: Path) -> bool:
    payload = build_paper_session_evidence_payload(
        db_path=base_dir / "trades.db",
        target_date=target_date,
    ).to_dict()

    print()
    print("=" * 72)
    print(f"  Paper Session Evidence - {target_date}")
    print("=" * 72)
    print(f"report_version                  : {payload['report_version']}")
    print(f"runtime_effect                  : {payload['runtime_effect']}")
    print(f"clean_for_authority_review      : {payload['clean_for_authority_review']}")

    print()
    print("Decision snapshots")
    for key, value in payload["decision_snapshots"].items():
        print(f"  {key:<38} {_fmt(value)}")

    print()
    print("Auto-buy / bridge")
    for key, value in payload["auto_buy"].items():
        print(f"  {key:<38} {_fmt(value)}")

    print()
    print("Candidate universe")
    for key in (
        "rows",
        "rows_with_forward_outcome",
        "missing_forward_outcome",
        "forward_outcome_coverage_rate",
        "non_taken_rows",
        "non_taken_with_forward_outcome",
        "non_taken_forward_outcome_coverage_rate",
    ):
        value = payload["candidate_universe"].get(key)
        if key.endswith("_rate"):
            value = _pct(value)
        print(f"  {key:<38} {_fmt(value)}")

    print()
    print("Outcomes")
    for key, value in payload["outcomes"].items():
        print(f"  {key:<38} {_fmt(value)}")

    if payload["blockers"]:
        print()
        print("Blockers")
        for blocker in payload["blockers"]:
            print(f"  - {blocker}")

    print()
    if payload["clean_for_authority_review"]:
        print("[OK] paper-session evidence has no authority-review blockers")
        return True
    print("[WARN] paper-session evidence has unresolved blockers")
    return False
