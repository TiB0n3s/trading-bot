#!/usr/bin/env python3
"""Tests for remaining assessment readiness services."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.feature_flag_change_history_service import (  # noqa: E402
    build_feature_flag_change_history_payload,
)
from services.full_session_paper_replay_service import (  # noqa: E402
    FullSessionReplayConfig,
    build_full_session_paper_replay_payload,
)
from services.incident_escalation_readiness_service import (  # noqa: E402
    build_incident_escalation_readiness_payload,
)
from services.packaged_entrypoint_validation_service import (  # noqa: E402
    build_packaged_entrypoint_validation_payload,
)


def test_full_session_paper_replay_plans_regular_session_cadence():
    payload = build_full_session_paper_replay_payload(
        FullSessionReplayConfig(
            symbols=("AAPL", "MSFT"),
            events_per_symbol_per_minute=2,
            execute=False,
        )
    )

    assert payload["planned_requests"] == 1560
    assert payload["executed_requests"] == 0
    assert payload["ready"] is True


def test_feature_flag_change_history_accepts_empty_existing_file():
    with TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        (base_dir / "ops").mkdir()
        (base_dir / "ops" / "feature_flag_change_history.jsonl").write_text("", encoding="utf-8")
        payload = build_feature_flag_change_history_payload(base_dir=base_dir)

    assert payload["ready"] is True
    assert payload["record_count"] == 0


def test_feature_flag_change_history_validates_required_fields():
    with TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        (base_dir / "ops").mkdir()
        (base_dir / "ops" / "feature_flag_change_history.jsonl").write_text(
            json.dumps({"flag": "LIVE_TRADING_ENABLED"}),
            encoding="utf-8",
        )
        payload = build_feature_flag_change_history_payload(base_dir=base_dir)

    assert payload["ready"] is False
    assert payload["errors"]


def test_incident_escalation_readiness_uses_metadata_and_alert_env():
    with TemporaryDirectory() as tmp:
        base_dir = Path(tmp)
        (base_dir / "ops").mkdir()
        (base_dir / "ops" / "incident_escalation.yml").write_text(
            """
version: incident_escalation_v1
cash_live_review_required: true
contacts:
  - role: primary_operator
severity_rules:
  critical:
    requires_external_alert: true
""",
            encoding="utf-8",
        )
        payload = build_incident_escalation_readiness_payload(
            base_dir=base_dir,
            env={"ALERT_WEBHOOK_URL": "https://example.invalid/hook"},
        )

    assert payload["ready"] is True
    assert payload["contact_count"] == 1
    assert payload["alert_destinations"] == ["ALERT_WEBHOOK_URL"]


def test_packaged_entrypoint_validation_reports_current_runtime_imports():
    payload = build_packaged_entrypoint_validation_payload(base_dir=ROOT)

    assert payload["ready"] is True
    assert payload["failed_count"] == 0


def main():
    tests = [
        test_full_session_paper_replay_plans_regular_session_cadence,
        test_feature_flag_change_history_accepts_empty_existing_file,
        test_feature_flag_change_history_validates_required_fields,
        test_incident_escalation_readiness_uses_metadata_and_alert_env,
        test_packaged_entrypoint_validation_reports_current_runtime_imports,
    ]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print(f"\nAll {len(tests)} remaining assessment service tests passed.")


if __name__ == "__main__":
    main()
