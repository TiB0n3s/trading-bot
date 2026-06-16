"""Tests for diagnostic configuration audit service.

Run:
  python3 tests/test_config_audit_service.py
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
sys.path.insert(0, str(ROOT))

from services.config_audit_service import (  # noqa: E402
    build_config_audit_payload,
    discover_env_var_references,
)
from services.runtime_safety_profile_service import (  # noqa: E402
    validate_runtime_safety_profile,
)

from src.trading_bot.config.authority_modes import (  # noqa: E402
    authority_mode_to_legacy_prediction_gate,
    normalize_config_authority_mode,
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
    assert payload["runtime_safety_profile"]["ready"] is False
    assert payload["runtime_safety_profile"]["safety_profile_hash"]
    assert (
        "cash execution mode requires LIVE_TRADING_ENABLED=true"
        in payload["runtime_safety_profile"]["warnings"]
    )


def test_build_config_audit_payload_allows_safe_paper_defaults(tmp_path):
    original_take_profit = os.environ.get("AUTO_BUY_TAKE_PROFIT_PCT")
    os.environ["AUTO_BUY_TAKE_PROFIT_PCT"] = "0"
    env = {
        "WEBHOOK_SECRET": "not-default",
        "EXECUTION_MODE": "paper",
        "LIVE_TRADING_ENABLED": "false",
        "ML_AUTHORITY_MODE": "observe_only",
        "TRANSFORMER_AUTHORITY_ENABLED": "false",
        "AUTO_BUY_TAKE_PROFIT_PCT": "2.0",
    }

    try:
        payload = build_config_audit_payload(base_dir=tmp_path, env=env)
    finally:
        if original_take_profit is None:
            os.environ.pop("AUTO_BUY_TAKE_PROFIT_PCT", None)
        else:
            os.environ["AUTO_BUY_TAKE_PROFIT_PCT"] = original_take_profit

    assert payload["warnings"] == []
    assert payload["factory_failures"] == 0
    assert payload["ready"] is True
    assert payload["runtime_safety_profile"]["ready"] is True


def test_authority_mode_normalization_maps_legacy_gate_terms():
    assert normalize_config_authority_mode("hard") == "live_block"
    assert normalize_config_authority_mode("soft") == "size_down"
    assert normalize_config_authority_mode("observe_only") == "observe"
    assert authority_mode_to_legacy_prediction_gate("live_block") == "hard"
    assert authority_mode_to_legacy_prediction_gate("size_down") == "soft"


def test_runtime_safety_profile_fail_fast_blocks_unsafe_live_config():
    env = {
        "EXECUTION_MODE": "cash_full",
        "LIVE_TRADING_ENABLED": "false",
        "ML_AUTHORITY_MODE": "live_block",
    }
    try:
        validate_runtime_safety_profile(env)
    except RuntimeError as exc:
        assert "unsafe runtime safety profile" in str(exc)
    else:
        raise AssertionError("unsafe runtime safety profile did not fail fast")


if __name__ == "__main__":
    tests = [
        test_discover_env_var_references_finds_literal_and_sensitive_keys,
        test_build_config_audit_payload_flags_unsafe_runtime_settings,
        test_build_config_audit_payload_allows_safe_paper_defaults,
        test_authority_mode_normalization_maps_legacy_gate_terms,
        test_runtime_safety_profile_fail_fast_blocks_unsafe_live_config,
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
