"""Operator report for external-symbol research candidates."""

from __future__ import annotations

from pathlib import Path

from services.intelligence.candidates.external_symbols import (
    DEFAULT_STATE_PATH,
    ExternalSymbolCandidateService,
)


def run_external_symbol_candidates(
    *,
    base_dir: Path,
    state_path: str | None = None,
    limit: int = 20,
) -> bool:
    path = Path(state_path) if state_path else base_dir / DEFAULT_STATE_PATH
    service = ExternalSymbolCandidateService(
        state_path=path,
        db_path=base_dir / "trades.db",
    )
    payload = service.report(limit=limit)

    print()
    print("=" * 72)
    print("  External Symbol Candidates")
    print("=" * 72)
    print(f"report_version          : {payload['report_version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"state_path              : {payload['state_path']}")
    print(f"updated_at              : {payload.get('updated_at') or '-'}")
    print(f"candidate_count         : {payload['candidate_count']}")

    print()
    print("Status counts")
    if payload["status_counts"]:
        for status, count in payload["status_counts"].items():
            print(f"  {status:<36} {count:>5}")
    else:
        print("  none")

    print()
    print("Candidates")
    if not payload["candidates"]:
        print("  none")
        print()
        print("[OK] no external-symbol candidates are queued")
        return True

    for row in payload["candidates"]:
        cov = row.get("coverage") or {}
        linked = ", ".join(row.get("linked_approved_symbols") or []) or "-"
        print(
            f"  {row.get('symbol'):<6} {row.get('status'):<34} "
            f"score={float(row.get('confidence_score') or 0):>5.1f} "
            f"mentions={int(row.get('mentions') or 0):>3} "
            f"trusted={int(row.get('trusted_mentions') or 0):>3} "
            f"rows={int(cov.get('rows') or 0):>7} "
            f"days={int(cov.get('trading_days') or 0):>4}"
        )
        print(f"         linked approved : {linked}")
        print(f"         reason          : {row.get('status_reason')}")

    if payload.get("truncated"):
        print()
        print(f"[WARN] output truncated to top {len(payload['candidates'])} candidates")

    print()
    print("[OK] external-symbol candidates are research-only; no trade authority changed")
    return True
