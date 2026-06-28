#!/usr/bin/env python3
"""Tests for historical-bar observe-only model readiness reporting."""

from __future__ import annotations

import io
import json
import sys
import tempfile
from contextlib import redirect_stdout
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from trading_bot.ops_checks.commands.historical_bar_model_checks import (  # noqa: E402
    run_historical_bar_model_readiness,
)


def _write_diag(
    path: Path,
    label: str,
    accuracy: float | None,
    *,
    generated_at: str = "2026-06-06T00:00:00+00:00",
    rows_loaded: int = 5900,
    trained: bool = True,
) -> None:
    training = {
        "trained": trained,
        "sample_size": rows_loaded,
    }
    if accuracy is not None:
        training["accuracy"] = accuracy
    payload = {
        "report_version": "historical_bar_observe_training_v1",
        "runtime_effect": "observe_only_no_live_authority",
        "model_id": f"historical_bar_{label}_20260606T000000Z",
        "label_target": label,
        "rows_loaded": rows_loaded,
        "symbol_count": 59,
        "generated_at": generated_at,
        "training": training,
    }
    path.write_text(json.dumps(payload), encoding="utf-8")


def test_historical_bar_model_readiness_reports_ready_candidates():
    with tempfile.TemporaryDirectory() as tmp:
        candidate_dir = Path(tmp)
        _write_diag(
            candidate_dir / "historical_bar_triple_barrier_label_20260606T000000Z.diagnostic.json",
            "triple_barrier_label",
            0.61,
        )
        _write_diag(
            candidate_dir / "historical_bar_trend_scan_label_20260606T000000Z.diagnostic.json",
            "trend_scan_label",
            0.58,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            ok = run_historical_bar_model_readiness(
                candidate_dir=candidate_dir,
                min_rows=5000,
                min_symbols=59,
                min_accuracy=0.50,
            )

    out = buf.getvalue()
    assert ok is True
    assert "historical_bar_model_readiness_v1" in out
    assert "observe_only_candidate_ready" in out
    assert "stale_binary_count" in out


def test_historical_bar_model_readiness_ignores_newer_failed_probe_when_trained_exists():
    with tempfile.TemporaryDirectory() as tmp:
        candidate_dir = Path(tmp)
        _write_diag(
            candidate_dir / "historical_bar_triple_barrier_label_20260607T000000Z.diagnostic.json",
            "triple_barrier_label",
            0.61,
            generated_at="2026-06-07T00:00:00+00:00",
            rows_loaded=5900,
            trained=True,
        )
        _write_diag(
            candidate_dir / "historical_bar_triple_barrier_label_20260608T000000Z.diagnostic.json",
            "triple_barrier_label",
            None,
            generated_at="2026-06-08T00:00:00+00:00",
            rows_loaded=59,
            trained=False,
        )
        buf = io.StringIO()
        with redirect_stdout(buf):
            ok = run_historical_bar_model_readiness(
                candidate_dir=candidate_dir,
                min_rows=5000,
                min_symbols=59,
                min_accuracy=0.50,
            )

    out = buf.getvalue()
    assert ok is True
    assert "triple_barrier_label   observe_only_candidate_ready" in out
    assert "rows=5900" in out
    assert "rows=59      " not in out


if __name__ == "__main__":
    test_historical_bar_model_readiness_reports_ready_candidates()
    print("[OK] test_historical_bar_model_readiness_reports_ready_candidates")
    test_historical_bar_model_readiness_ignores_newer_failed_probe_when_trained_exists()
    print("[OK] test_historical_bar_model_readiness_ignores_newer_failed_probe_when_trained_exists")
