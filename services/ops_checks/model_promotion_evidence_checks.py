"""Operator report for model-promotion evidence artifacts."""

from __future__ import annotations

from pathlib import Path

from services.model_promotion_evidence_service import build_model_promotion_evidence_payload


def run_model_promotion_evidence_report(
    *,
    base_dir: Path,
    write: bool = False,
    operator: str = "unassigned",
    approval_reference: str = "",
    replay_symbols: tuple[str, ...] = ("AAPL",),
    execute_replay: bool = False,
    max_replay_requests: int = 1000,
) -> bool:
    payload = build_model_promotion_evidence_payload(
        base_dir=base_dir,
        write=write,
        operator=operator,
        approval_reference=approval_reference,
        replay_symbols=replay_symbols,
        execute_replay=execute_replay,
        max_replay_requests=max_replay_requests,
    )
    print()
    print("=" * 72)
    print("  Model Promotion Evidence")
    print("=" * 72)
    print(f"report_version          : {payload['report_version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")
    print(f"evidence_dir            : {payload['evidence_dir']}")
    print(f"write                   : {payload['write']}")
    print(f"artifact_count          : {payload['artifact_count']}")
    print(f"ready_count             : {payload['ready_count']}")
    print(f"ready_live_promotion    : {payload['ready_for_live_promotion']}")
    print()
    for name, artifact in payload["artifacts"].items():
        status = "ready" if artifact.get("ready") is True else "not_ready"
        reason = (
            artifact.get("reason")
            or artifact.get("baseline_requirement")
            or artifact.get("source")
            or "-"
        )
        print(f"  {name:<32} {status:<10} {reason}")
    print()
    if payload["write"]:
        print("[OK] promotion evidence artifacts written")
    elif payload["ready_for_live_promotion"]:
        print("[OK] promotion evidence is complete")
    else:
        print("[WARN] promotion evidence is incomplete")
    return bool(payload["write"] or payload["ready_for_live_promotion"])
