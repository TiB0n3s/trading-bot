#!/usr/bin/env python3
"""Tests for shared pipeline runner controls."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pipeline import Step, run_pipeline  # noqa: E402


def test_pipeline_step_marker_skips_completed_step():
    with tempfile.TemporaryDirectory() as tmp:
        base = Path(tmp)
        module_path = base / "marker_step.py"
        counter_path = base / "counter.txt"
        marker_path = base / "markers" / "step.json"
        module_path.write_text(
            "\n".join(
                [
                    "from pathlib import Path",
                    f"COUNTER = Path({str(counter_path)!r})",
                    "def main():",
                    "    current = int(COUNTER.read_text()) if COUNTER.exists() else 0",
                    "    COUNTER.write_text(str(current + 1))",
                    "    return 0",
                ]
            )
            + "\n",
            encoding="utf-8",
        )
        sys.path.insert(0, str(base))
        try:
            step = Step(
                name="marker_step",
                module="marker_step",
                argv=[],
                marker_path=marker_path,
            )
            first = run_pipeline("test_pipeline", [step], "2026-06-03")
            second = run_pipeline("test_pipeline", [step], "2026-06-03")
        finally:
            sys.path.remove(str(base))

        assert first.ok is True
        assert second.ok is True
        assert marker_path.exists()
        assert counter_path.read_text() == "1"
        assert second.steps[0].skipped is True


if __name__ == "__main__":
    test_pipeline_step_marker_skips_completed_step()
    print("[OK] pipeline runner tests passed")
