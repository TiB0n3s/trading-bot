#!/usr/bin/env python3
"""Tests for paper replay/load probe."""

from __future__ import annotations

import sys
from pathlib import Path
from tempfile import TemporaryDirectory

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from services.paper_replay_load_probe_service import (  # noqa: E402
    PaperReplayLoadProbeConfig,
    run_paper_replay_load_probe,
)


def test_paper_replay_load_probe_writes_signal_and_fill_rows():
    with TemporaryDirectory() as tmp:
        db_path = Path(tmp) / "probe.db"
        payload = run_paper_replay_load_probe(
            PaperReplayLoadProbeConfig(
                requests=6,
                concurrency=2,
                symbol="AAPL",
                action="buy",
                db_path=db_path,
            )
        )

    assert payload["runtime_effect"] == "diagnostic_only_temp_db_no_broker_orders"
    assert payload["passed"] is True
    assert payload["ok_count"] == 6
    assert payload["signal_rows"] == 6
    assert payload["fill_rows"] == 6


def main():
    tests = [test_paper_replay_load_probe_writes_signal_and_fill_rows]
    for test in tests:
        test()
        print(f"[OK] {test.__name__}")

    print(f"\nAll {len(tests)} paper replay/load probe tests passed.")


if __name__ == "__main__":
    main()
