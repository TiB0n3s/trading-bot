"""Operator report for cross-layer model verification."""

from __future__ import annotations

from pathlib import Path

from repositories.ops_check_repo import OpsCheckRepository
from services.cross_layer_verification_service import build_cross_layer_verification_payload


def _fmt(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, float):
        return f"{value:.4f}"
    return str(value)


def run_cross_layer_verification_report(target_date: str, *, base_dir: Path) -> bool:
    print()
    print("=" * 72)
    print(f"  Cross-Layer Verification Matrix - {target_date}")
    print("=" * 72)

    db_path = base_dir / "trades.db"
    if not db_path.exists():
        print(f"[WARN] trades.db not found: {db_path}")
        return False

    rows = [dict(row) for row in OpsCheckRepository(db_path).decision_authority_rows(target_date)]
    payload = build_cross_layer_verification_payload(rows, target_date=target_date).to_dict()
    print(f"report_version          : {payload['report_version']}")
    print(f"runtime_effect          : {payload['runtime_effect']}")

    summary = payload["summary"]
    print()
    print("Layered payload coverage")
    print(f"  decision_rows         : {summary['decision_rows']}")
    print(f"  layered_rows          : {summary['layered_rows']}")
    print(f"  layered_coverage_rate : {_fmt(summary['layered_coverage_rate'])}")
    print(f"  veto_rate             : {_fmt(summary['veto_rate'])}")

    drift = payload["drift_relaxation_symmetry"]
    print()
    print("Drift / relaxation symmetry")
    print(f"  status                : {drift['status']}")
    print(f"  severe_drift          : {drift['severe_drift']}")
    print(f"  max_psi               : {_fmt(drift['max_psi'])}")
    print(f"  relaxation_active     : {drift['relaxation_active_rows']}")
    print(f"  drift_disabled        : {drift['drift_disabled_rows']}")
    print(f"  high_unveto_rows      : {drift['high_unveto_rows']}")
    print(f"  avg_p_unveto          : {_fmt(drift['avg_p_unveto'])}")

    handshake = payload["veto_to_sizing_handshake"]
    print()
    print("Veto-to-sizing handshake")
    print(f"  status                : {handshake['status']}")
    print(f"  marginal_approvals    : {handshake['marginal_approval_rows']}")
    print(f"  scaled_down_rows      : {handshake['marginal_scaled_down_rows']}")
    print(f"  scaled_down_rate      : {_fmt(handshake['marginal_scaled_down_rate'])}")
    print(f"  avg_size_ratio        : {_fmt(handshake['avg_marginal_size_ratio'])}")

    translation = payload["marginal_risk_translation"]
    print()
    print("Marginal risk translation")
    print(f"  status                : {translation['status']}")
    print(f"  rows                  : {translation['rows']}")
    print(f"  corr(score,size)      : {_fmt(translation['correlation'])}")
    print(f"  avg_allocation_mult   : {_fmt(translation['avg_allocation_multiplier'])}")
    print(f"  near_max_alloc_rate   : {_fmt(translation['near_max_allocation_rate'])}")

    anomaly = payload["cross_layer_anomaly"]
    print()
    print("Level 0 / Level 2 anomaly scan")
    print(f"  status                : {anomaly['status']}")
    print(f"  stable_low_l2_rows    : {anomaly['stable_level0_low_level2_rows']}")
    print(f"  affected_symbols      : {anomaly['stable_level0_low_level2_symbols']}")
    print(f"  avg_low_l2_score      : {_fmt(anomaly['avg_low_level2_score'])}")

    warnings = payload["warnings"]
    if warnings:
        print()
        for warning in warnings:
            print(f"[WARN] {warning}")
        return False

    print()
    print("[OK] cross-layer verification matrix has no current warnings")
    return True
