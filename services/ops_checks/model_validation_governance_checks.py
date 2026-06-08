"""Operator report for consolidated model validation governance."""

from __future__ import annotations

from services.model_validation_governance_service import build_model_validation_governance_payload


def run_model_validation_governance_report(
    *,
    min_rows: int = 5000,
    min_symbols: int = 20,
    min_accuracy: float = 0.50,
    limit: int = 12,
) -> bool:
    payload = build_model_validation_governance_payload(
        min_rows=min_rows,
        min_symbols=min_symbols,
        min_accuracy=min_accuracy,
    )

    print()
    print("=" * 72)
    print("  Model Validation Governance")
    print("=" * 72)
    print(f"report_version              : {payload['report_version']}")
    print(f"runtime_effect              : {payload['runtime_effect']}")
    print(f"labels_assessed             : {payload['labels_assessed']}")
    print(f"ready_label_count           : {payload['ready_label_count']}")
    print(f"registry_entry_count        : {payload['registry_entry_count']}")
    print(f"live_registry_entry_count   : {payload['live_registry_entry_count']}")
    print(f"ready_observe_only          : {payload['ready_for_observe_only_validation']}")
    print(f"ready_live_promotion        : {payload['ready_for_live_promotion']}")

    print()
    print("Candidates")
    for row in payload["candidates"][:limit]:
        accuracy = "-" if row["accuracy"] is None else f"{row['accuracy']:.4f}"
        failed = ",".join(row["failed_thresholds"]) if row["failed_thresholds"] else "-"
        print(
            f"  {row['label_target']:<22} {row['status']:<20} "
            f"rows={row['rows_loaded']:<7} symbols={row['symbol_count']:<3} "
            f"accuracy={accuracy:<7} failed={failed}"
        )
        print(f"    model_id={row['model_id']}")

    print()
    print("Blockers")
    all_blockers = payload["blockers"] + payload["promotion_evidence_blockers"]
    if all_blockers:
        for blocker in all_blockers:
            print(f"  - {blocker}")
    else:
        print("  none")

    print()
    print("Promotion Evidence")
    for row in payload["promotion_evidence"]:
        status = "ready" if row["ready"] else "missing_or_not_ready"
        print(f"  {row['name']:<30} {status:<20} {row['path']}")

    print()
    for note in payload["notes"]:
        print(f"  note: {note}")

    print()
    if payload["ready_for_observe_only_validation"]:
        print("[OK] model governance report is ready for observe-only validation")
        return True
    print("[WARN] model governance report found validation blockers")
    return False
