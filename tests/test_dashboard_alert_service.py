#!/usr/bin/env python3
"""Tests for dashboard alert payloads."""

from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.dashboard_alert_service import build_earnings_dashboard_alert


def test_build_earnings_dashboard_alert_is_payload_only():
    alert = build_earnings_dashboard_alert(
        symbol="NVDA",
        sentiment={"label": "positive", "score": 7, "model_provider": "lexicon"},
        earnings_contract={"peer_watchlist": ["AMD", "AVGO"]},
    ).to_dict()

    assert alert["runtime_effect"] == "payload_only_no_external_post"
    assert "NVDA" in alert["title"]
    assert "AMD" in alert["markdown"]


def main():
    test_build_earnings_dashboard_alert_is_payload_only()
    print("[OK] test_build_earnings_dashboard_alert_is_payload_only")
    print("\nAll 1 dashboard alert service tests passed.")


if __name__ == "__main__":
    main()
