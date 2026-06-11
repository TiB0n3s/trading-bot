"""Tests for architecture surface audit diagnostics.

Run:
  python3 tests/test_architecture_surface_audit_service.py
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from services.architecture_surface_audit_service import (  # noqa: E402
    SRC_CONTEXTS,
    build_architecture_surface_payload,
)


def _write(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text)


def _create_skeleton(base: Path) -> None:
    root = base / "src" / "trading_bot"
    root.mkdir(parents=True, exist_ok=True)
    _write(root / "__init__.py", "")
    for context in SRC_CONTEXTS:
        _write(root / context / "__init__.py", "")


def test_architecture_surface_payload_counts_core_surfaces(tmp_path):
    _write(tmp_path / "app.py", "import os\nVALUE = os.getenv('APP_FLAG')\n")
    _write(tmp_path / "worker.py", "print('worker')\n")
    _write(tmp_path / "services" / "approval_service.py", "print('service')\n")
    _write(tmp_path / "services" / "signal_pipeline.py", "print('pipeline')\n")
    _write(tmp_path / "services" / "decision" / "orchestrator.py", "print('orchestrator')\n")
    _write(
        tmp_path / "services" / "signal_runtime_wiring.py",
        "from services.decision import CanonicalDecisionOrchestrator\n",
    )
    _write(
        tmp_path / "services" / "auto_buy_execution_service.py",
        "def auto_buy_execution_authority():\n    return 'missing canonical decision trace'\n",
    )
    _write(
        tmp_path / "src" / "trading_bot" / "ops_checks" / "runtime_checks.py",
        "print('check')\n",
    )
    _write(tmp_path / "repositories" / "trades_repo.py", "print('repo')\n")
    _write(tmp_path / "ops" / "compatibility_deletion_plan.md", "# plan\n")
    _write(
        tmp_path / "legacy_architecture" / "decision_v1" / "manifest.json",
        json.dumps(
            {
                "version": "decision_v1_legacy_manifest_v1",
                "runtime_effect": "classification_only_no_runtime_change",
                "canonical_package": "services/decision",
                "surfaces": [
                    {
                        "path": "services/signal_pipeline.py",
                        "bucket": "thin_adapter",
                        "replacement": "services/decision/engine.py",
                    },
                    {
                        "path": "scripts/missing_legacy.py",
                        "bucket": "manual_tool",
                        "replacement": "ops/manual_tools",
                    },
                ],
            }
        ),
    )
    _create_skeleton(tmp_path)

    payload = build_architecture_surface_payload(base_dir=tmp_path)
    metrics = {row["name"]: row for row in payload["surface_metrics"]}

    assert payload["version"] == "architecture_surface_audit_v1"
    assert payload["runtime_effect"] == "diagnostic_only_no_runtime_change"
    assert metrics["root_python_files"]["current"] == 2
    assert metrics["services_direct_modules"]["current"] == 4
    assert metrics["services_ops_check_modules"]["current"] == 2
    assert metrics["repository_modules"]["current"] == 1
    assert payload["raw_env_files"] == 1
    assert payload["raw_env_keys"] == 1
    assert payload["compatibility_plan_exists"] is True
    assert payload["src_skeleton"]["contexts_ready"] == len(SRC_CONTEXTS)
    assert payload["legacy_decision_v1"]["exists"] is True
    assert payload["legacy_decision_v1"]["surfaces_count"] == 2
    assert payload["legacy_decision_v1"]["existing_surfaces_count"] == 1
    assert payload["legacy_decision_v1"]["missing_surfaces_count"] == 1
    assert payload["legacy_decision_v1"]["buckets"]["thin_adapter"] == 1
    assert payload["legacy_decision_v1"]["ownership_status"]["ready"] is True


def test_architecture_surface_payload_flags_missing_skeleton(tmp_path):
    _write(tmp_path / "app.py", "print('app')\n")

    payload = build_architecture_surface_payload(base_dir=tmp_path)

    assert payload["src_skeleton"]["root_exists"] is False
    assert payload["src_skeleton"]["contexts_ready"] == 0
    assert payload["legacy_decision_v1"]["exists"] is False
    assert payload["ready"] is False


def test_architecture_surface_top_files_ignore_virtualenvs(tmp_path):
    _write(tmp_path / "src" / "trading_bot" / "real_module.py", "print('ok')\n")
    _write(tmp_path / "venv-webull" / "lib" / "site-packages" / "huge.py", "x = 1\n" * 2000)
    _create_skeleton(tmp_path)

    payload = build_architecture_surface_payload(base_dir=tmp_path)
    top_paths = {row["path"] for row in payload["top_python_files"]}

    assert "src/trading_bot/real_module.py" in top_paths
    assert not any(path.startswith("venv-webull/") for path in top_paths)


if __name__ == "__main__":
    tests = [
        test_architecture_surface_payload_counts_core_surfaces,
        test_architecture_surface_payload_flags_missing_skeleton,
        test_architecture_surface_top_files_ignore_virtualenvs,
    ]
    for test in tests:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            test(Path(tmp))
        print(f"[OK] {test.__name__}")

    print()
    print(f"All {len(tests)} architecture surface audit tests passed.")
