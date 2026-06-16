#!/usr/bin/env python3
"""Run fast safety checks for commits, CI, and operator wrappers.

This intentionally targets the core risk/authority/architecture tests instead
of the full legacy suite. Full-suite runs remain available through run_tests.py.
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
VENV_PYTHON = ROOT / "venv" / "bin" / "python"

SAFETY_TESTS = [
    "tests/test_risk_core.py",
    "tests/test_slippage_kelly_sizing_service.py",
    "tests/test_supervised_prediction_training_service.py",
    "tests/test_model_validation_governance_service.py",
    "tests/test_ml_promotion.py",
    "tests/test_ml_lifecycle_contracts.py",
    "tests/test_ml_promotion_metrics_service.py",
    "tests/test_transformer_authority_model_service.py",
    "tests/test_decision_policy.py",
    "tests/test_context_approval_sizing_services.py",
    "tests/test_auto_buy_execution_service.py",
    "tests/test_runtime_decision_engine_contracts.py",
    "tests/test_decision_trace_reports.py",
    "tests/test_decision_snapshot_service.py",
    "tests/test_market_context_output_paths.py",
    "tests/test_cot_positioning.py",
    "tests/test_prime_brokerage_flows.py",
    "tests/test_dealer_gamma.py",
    "tests/test_rolling_momentum_service.py",
    "tests/test_volume_clock_vpin_service.py",
    "tests/test_volatile_session_intelligence_service.py",
    "tests/test_config_audit_service.py",
    "tests/test_feature_flag_inventory_service.py",
    "tests/test_secrets_hygiene_checks.py",
    "tests/test_database_backup_service.py",
    "tests/test_observability_health_checks.py",
    "tests/test_operational_readiness_service.py",
    "tests/test_external_readiness_services.py",
    "tests/test_incident_workflow_service.py",
    "tests/test_architecture_surface_audit_service.py",
    "tests/test_deployment_reference_audit.py",
    "tests/test_dependency_packaging_contract.py",
    "tests/test_optional_dependency_service.py",
    "tests/test_ops_check_registry.py",
    "tests/test_architecture_boundaries.py",
]

FULL_SAFETY_TESTS = [
    *SAFETY_TESTS,
    "tests/test_remaining_assessment_services.py",
    "tests/test_local_load_probe_service.py",
    "tests/test_paper_replay_load_probe_service.py",
]


def reexec_under_venv_if_available() -> None:
    if not VENV_PYTHON.exists():
        return
    venv_dir = VENV_PYTHON.parent.parent.resolve()
    if Path(sys.prefix).resolve() == venv_dir:
        return
    os.execv(str(VENV_PYTHON), [str(VENV_PYTHON), str(Path(__file__).resolve()), *sys.argv[1:]])


def main() -> int:
    reexec_under_venv_if_available()
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--full",
        action="store_true",
        help="Include heavier assessment/load-probe tests that are not suitable for pre-commit.",
    )
    args = parser.parse_args()

    selected_tests = FULL_SAFETY_TESTS if args.full else SAFETY_TESTS
    env = os.environ.copy()
    pythonpath_parts = [str(ROOT / "scripts"), str(ROOT), str(ROOT / "src")]
    if env.get("PYTHONPATH"):
        pythonpath_parts.append(env["PYTHONPATH"])
    env["PYTHONPATH"] = os.pathsep.join(pythonpath_parts)
    print("=" * 72)
    print("  Trading Bot Fast Safety Checks")
    print("=" * 72)
    print("runtime_effect=none")
    print(f"scope={'full' if args.full else 'pre_commit_fast'}")
    if not args.full:
        print(
            "excluded_from_fast_hook=remaining_assessment,local_load_probe,paper_replay_load_probe"
        )

    result = subprocess.run(
        [sys.executable, "-m", "pytest", *selected_tests],
        cwd=ROOT,
        env=env,
    )

    print()
    print("=" * 72)
    if result.returncode != 0:
        print("[FAIL] safety test run failed")
        return result.returncode
    print(f"[OK] all {len(selected_tests)} safety test file(s) passed")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
