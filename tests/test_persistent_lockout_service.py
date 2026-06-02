#!/usr/bin/env python3
"""Tests for persistent risk lockout state."""

from __future__ import annotations

import tempfile
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from services.persistent_lockout_service import PersistentLockoutService


def test_persistent_lockout_service_round_trip():
    with tempfile.TemporaryDirectory() as tmp:
        path = Path(tmp) / "risk_lockout.json"
        service = PersistentLockoutService(path)

        assert service.read().active is False
        active = service.activate(reason="crash_regime")
        assert active.active is True
        assert service.read().status == "lockout"
        rebuilding = service.set_rebuilding(reason="quiet_bull_reentry")
        assert rebuilding.status == "rebuilding"
        cleared = service.clear(reason="done")
        assert cleared.active is False
        assert service.read().status == "normal"


def main():
    test_persistent_lockout_service_round_trip()
    print("[OK] test_persistent_lockout_service_round_trip")
    print("\nAll 1 persistent lockout service tests passed.")


if __name__ == "__main__":
    main()
