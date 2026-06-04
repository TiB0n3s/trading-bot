"""Operator report for advanced alpha readiness."""

from __future__ import annotations

from pathlib import Path

from services.advanced_alpha_readiness_service import (
    build_advanced_alpha_readiness_payload,
)


def run_advanced_alpha_readiness(
    target_date: str,
    *,
    base_dir: Path,
) -> bool:
    print()
    print("=" * 72)
    print(f"  Advanced Alpha Readiness - {target_date}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    payload = build_advanced_alpha_readiness_payload(
        target_date=target_date,
        db_path=db_path,
    )
    data = payload.to_dict()
    summary = data["summary"]

    print(f"report_version          : {data['report_version']}")
    print(f"runtime_effect          : {data['runtime_effect']}")
    print(f"rows                    : {summary['rows']}")
    print(f"rows_with_forward       : {summary['rows_with_forward_outcome']}")
    print(f"order_flow_coverage     : {summary['order_flow_coverage_rate']:.2f}%")
    print(f"fractional_memory_cov   : {summary['fractional_memory_coverage_rate']:.2f}%")
    print(f"authority_ready         : {summary['authority_ready']}")

    print()
    print(
        f"  {'family':<34} {'status':<28} {'ready':>8} "
        f"{'checks':>9} {'failed'}"
    )
    print(f"  {'-' * 34} {'-' * 28} {'-' * 8} {'-' * 9} {'-' * 32}")
    for item in data["items"]:
        failed = ", ".join(item["failed"][:4]) if item["failed"] else "-"
        if len(item["failed"]) > 4:
            failed += ", ..."
        print(
            f"  {item['feature_family']:<34} "
            f"{item['status']:<28} "
            f"{item['readiness_pct']:>7.2f}% "
            f"{item['passed_checks']:>2}/{item['total_checks']:<6} "
            f"{failed}"
        )
        print(f"    capability: {item['current_capability']}")
        print(f"    next      : {item['next_action']}")

    print()
    print("[OK] advanced alpha readiness completed; no live authority changed")
    return True
