"""Tests for diagnostic configuration audit service.

Run:
  python3 tests/test_config_audit_service.py
"""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.config_audit_service import (  # noqa: E402
    build_config_audit_payload,
    discover_env_var_references,
)


def test_discover_env_var_references_finds_literal_and_sensitive_keys(tmp_path):
    source = tmp_path / "sample.py"
    source.write_text(
        "\n".join(
            [
                "import os",
                "WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET')",
                "MODE = os.environ.get('EXECUTION_MODE', 'paper')",
                "name = 'DYNAMIC_ENV'",
                "VALUE = os.getenv(name)",
            ]
        )
    )

    payload = discover_env_var_references(tmp_path)

    assert payload["total_env_keys"] == 2
    assert payload["env_keys"]["WEBHOOK_SECRET"] == ["sample.py"]
    assert payload["env_keys"]["EXECUTION_MODE"] == ["sample.py"]
    assert payload["sensitive_env_keys"] == ["WEBHOOK_SECRET"]
    assert payload["non_literal_call_files"] == ["sample.py"]


def test_build_config_audit_payload_flags_unsafe_runtime_settings(tmp_path):
    env = {
        "WEBHOOK_SECRET": "changeme",
        "ALLOW_QUERY_STRING_SECRET": "true",
        "EXECUTION_MODE": "cash_full",
        "LIVE_TRADING_ENABLED": "false",
        "ML_AUTHORITY_MODE": "live_block",
        "TRANSFORMER_AUTHORITY_ENABLED": "true",
    }

    payload = build_config_audit_payload(base_dir=tmp_path, env=env)

    assert payload["version"] == "config_audit_v1"
    assert payload["runtime_effect"] == "diagnostic_only_no_runtime_config_change"
    assert payload["execution_mode"] == "cash_full"
    assert payload["live_trading_enabled"] is False
    assert payload["factory_failures"] == 0
    assert payload["ready"] is False
    assert "WEBHOOK_SECRET is unset or still using the unsafe default" in payload["warnings"]
    assert "ALLOW_QUERY_STRING_SECRET is enabled" in payload["warnings"]
    assert "EXECUTION_MODE=cash_full requires explicit operator review" in payload["warnings"]
    assert "ML_AUTHORITY_MODE=live_block requires current promotion evidence" in payload["warnings"]
    assert "Transformer authority enabled without TRANSFORMER_MODEL_ID" in payload["warnings"]


def test_build_config_audit_payload_allows_safe_paper_defaults(tmp_path):
    env = {
        "WEBHOOK_SECRET": "not-default",
        "EXECUTION_MODE": "paper",
        "LIVE_TRADING_ENABLED": "false",
        "ML_AUTHORITY_MODE": "observe_only",
        "TRANSFORMER_AUTHORITY_ENABLED": "false",
    }

    payload = build_config_audit_payload(base_dir=tmp_path, env=env)

    assert payload["warnings"] == []
    assert payload["ready"] is True


if __name__ == "__main__":
    tests = [
        test_discover_env_var_references_finds_literal_and_sensitive_keys,
        test_build_config_audit_payload_flags_unsafe_runtime_settings,
        test_build_config_audit_payload_allows_safe_paper_defaults,
    ]
    for test in tests:
        if test.__code__.co_argcount:
            import tempfile

            with tempfile.TemporaryDirectory() as tmp:
                test(Path(tmp))
        else:
            test()
        print(f"[OK] {test.__name__}")

    print()
    print(f"All {len(tests)} config audit service tests passed.")
